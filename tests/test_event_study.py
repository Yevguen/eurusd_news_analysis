"""Tests for event alignment, windows, returns, volatility and diagnostics."""

import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.data_governance.source_registry import load_source_registry
from src.economic_calendar.historical_models import DataOrigin, HistoricalRelease
from src.economic_calendar.historical_storage import HistoricalReleaseStorage
from src.impact_analysis.consensus import evaluate_consensus
from src.impact_analysis.event_study import (
    ConsensusStatus,
    EventWindowSpec,
    MarketDataCoverageError,
    MissingCandlesError,
    TimeBasisError,
    align_event,
    compute_metrics,
    extract_window,
    run_event_study,
    server_offset_volume_diagnostic,
)
from src.impact_analysis.price_data import PriceDataOrigin, load_mt5_h1_csv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_sources.yaml"
DEMO_DIR = PROJECT_ROOT / "data" / "demo"

UTC = timezone.utc
PLUS_TWO = timedelta(hours=2)
NO_CONSENSUS = ConsensusStatus(available=False, reason="test")


def make_candles(
    first_server_open: datetime,
    closes: list[float],
    *,
    volumes: list[int] | None = None,
    first_open: float | None = None,
) -> pd.DataFrame:
    """Contiguous H1 candles; each open equals the previous close."""

    rows = []
    previous = closes[0] if first_open is None else first_open

    for index, close in enumerate(closes):
        rows.append(
            {
                "server_open_time": first_server_open + timedelta(hours=index),
                "open": previous,
                "high": max(previous, close) + 0.0002,
                "low": min(previous, close) - 0.0002,
                "close": close,
                "tick_volume": 1000 if volumes is None else volumes[index],
                "spread": 1,
            }
        )
        previous = close

    frame = pd.DataFrame(rows)
    frame["server_open_time"] = frame["server_open_time"].astype("datetime64[ns]")
    return frame


def make_release(
    official: str, mt5: str, *, release_id: str = "us_cpi_test"
) -> HistoricalRelease:
    official_time = datetime.fromisoformat(official)
    return HistoricalRelease(
        release_id=release_id,
        event_key="us_cpi",
        official_release_time=official_time,
        utc_release_time=official_time.astimezone(UTC),
        mt5_server_time=datetime.fromisoformat(mt5),
        official_source_name="Test source",
        release_summary="Test release.",
        data_origin=DataOrigin.AUTHENTIC,
    )


# ---------------------------------------------------------------------------
# Alignment and timezone handling
# ---------------------------------------------------------------------------


def test_release_inside_candle_maps_to_containing_candle() -> None:
    alignment = align_event(datetime(2024, 1, 11, 13, 30, tzinfo=UTC), PLUS_TWO)

    assert alignment.event_candle_open_utc == datetime(2024, 1, 11, 13, tzinfo=UTC)
    assert alignment.event_candle_open_server == datetime(2024, 1, 11, 15)
    assert alignment.event_time_server == datetime(2024, 1, 11, 15, 30)
    assert alignment.minutes_into_event_candle == 30
    assert not alignment.falls_on_candle_open


def test_release_on_the_hour_opens_the_event_candle() -> None:
    alignment = align_event(datetime(2024, 1, 31, 19, 0, tzinfo=UTC), PLUS_TWO)

    assert alignment.event_candle_open_utc == datetime(2024, 1, 31, 19, tzinfo=UTC)
    assert alignment.falls_on_candle_open


def test_non_utc_input_is_converted_before_alignment() -> None:
    eastern = datetime.fromisoformat("2024-01-11T08:30:00-05:00")

    assert align_event(eastern, PLUS_TWO) == align_event(
        datetime(2024, 1, 11, 13, 30, tzinfo=UTC), PLUS_TWO
    )


def test_naive_event_time_is_rejected() -> None:
    with pytest.raises(TimeBasisError):
        align_event(datetime(2024, 1, 11, 13, 30), PLUS_TWO)


def test_window_crossing_dst_transition_is_rejected() -> None:
    # US daylight saving started on 2024-03-10 at 07:00 UTC; a 31-candle
    # look-back from Monday 11 March 13:00 UTC crosses it.
    release = make_release("2024-03-11T09:30:00-04:00", "2024-03-11T15:30:00+02:00")
    candles = make_candles(datetime(2024, 3, 8), [1.0] * 120)

    with pytest.raises(TimeBasisError, match="America/New_York"):
        run_event_study(
            release,
            candles,
            price_data_origin=PriceDataOrigin.SYNTHETIC,
            price_source_description="test",
            consensus=NO_CONSENSUS,
        )


def test_summer_event_with_winter_offset_is_flagged() -> None:
    release = make_release("2024-07-11T08:30:00-04:00", "2024-07-11T14:30:00+02:00")
    candles = make_candles(datetime(2024, 7, 10), [1.0 + 0.0001 * i for i in range(48)])

    result = run_event_study(
        release,
        candles,
        price_data_origin=PriceDataOrigin.SYNTHETIC,
        price_source_description="test",
        consensus=NO_CONSENSUS,
    )

    assert any("daylight-saving period" in item for item in result.limitations)


# ---------------------------------------------------------------------------
# Windows, returns and volatility
# ---------------------------------------------------------------------------

SMALL_SPEC = EventWindowSpec(pre_candles=2, post_candles=2, baseline_candles=3)

# Closes for k = -6 (anchor) .. +2 with the event candle at k = 0.
HAND_CLOSES = [1.0000, 1.0010, 0.9990, 1.0000, 1.0005, 1.0000, 1.0100, 1.0050, 1.0150]


def hand_window():
    alignment = align_event(datetime(2024, 1, 11, 13, 30, tzinfo=UTC), PLUS_TWO)
    # Anchor k = -6 opens at 15:00 - 6 h = 09:00 server time.
    candles = make_candles(datetime(2024, 1, 11, 9), HAND_CLOSES, first_open=1.0000)
    return alignment, extract_window(candles, alignment, SMALL_SPEC)


def test_window_has_contiguous_relative_indices() -> None:
    alignment, window = hand_window()

    assert window["relative_index"].tolist() == list(range(-6, 3))
    assert window["server_open_time"].iloc[6] == pd.Timestamp("2024-01-11 15:00")
    assert window["open_time_utc"].iloc[6] == alignment.event_candle_open_utc


def test_return_and_volatility_formulas() -> None:
    _, window = hand_window()
    metrics = compute_metrics(window, SMALL_SPEC)

    def bp(a: float, b: float) -> float:
        return 10_000 * math.log(a / b)

    closes = dict(zip(range(-6, 3), HAND_CLOSES, strict=True))
    baseline = [bp(closes[k], closes[k - 1]) for k in (-5, -4, -3)]
    post = [bp(closes[k], closes[k - 1]) for k in (1, 2)]

    assert metrics["reference_close"] == pytest.approx(1.0000)
    assert metrics["event_candle_return_bp"] == pytest.approx(bp(1.0100, 1.0000))
    assert metrics["baseline_volatility_bp"] == pytest.approx(
        statistics.stdev(baseline)
    )
    assert metrics["post_event_realized_volatility_bp"] == pytest.approx(
        statistics.stdev(post)
    )
    assert metrics["event_abs_return_in_baseline_sigmas"] == pytest.approx(
        abs(bp(1.0100, 1.0000)) / statistics.stdev(baseline)
    )
    # Pre-event drift: open of k = -2 (close of k = -3) to close of k = -1.
    assert metrics["pre_event_drift_bp"] == pytest.approx(bp(1.0000, 1.0000))
    assert metrics["cumulative_return_bp_to_close_k2"] == pytest.approx(bp(1.0150, 1.0))
    assert metrics["price_change_pips_to_close_k2"] == pytest.approx(150.0)
    assert metrics["event_candle_range_pips"] == pytest.approx(
        (1.0100 + 0.0002 - (1.0000 - 0.0002)) * 10_000
    )


def test_missing_candle_inside_window_raises() -> None:
    alignment = align_event(datetime(2024, 1, 11, 13, 30, tzinfo=UTC), PLUS_TWO)
    candles = make_candles(datetime(2024, 1, 11, 9), HAND_CLOSES)
    candles = candles.drop(index=4).reset_index(drop=True)

    with pytest.raises(MissingCandlesError) as exc_info:
        extract_window(candles, alignment, SMALL_SPEC)

    assert exc_info.value.missing_server_opens == [datetime(2024, 1, 11, 13)]
    assert "never filled" in str(exc_info.value)


def test_event_outside_price_data_raises() -> None:
    alignment = align_event(datetime(2024, 2, 1, 13, 30, tzinfo=UTC), PLUS_TWO)
    candles = make_candles(datetime(2024, 1, 11, 9), HAND_CLOSES)

    with pytest.raises(MarketDataCoverageError, match="does not cover"):
        extract_window(candles, alignment, SMALL_SPEC)


def test_window_spec_rejects_too_short_windows() -> None:
    with pytest.raises(ValueError):
        EventWindowSpec(pre_candles=1)


# ---------------------------------------------------------------------------
# Server-offset diagnostic
# ---------------------------------------------------------------------------


def test_offset_diagnostic_identifies_clear_volume_jump() -> None:
    volumes = [1000] * 12
    volumes[7] = 5000  # server 15:00 = 13:00 UTC under +2
    volumes[8] = 5200  # stays high afterwards, as in real sessions
    candles = make_candles(datetime(2024, 1, 11, 8), [1.0] * 12, volumes=volumes)

    diagnostic = server_offset_volume_diagnostic(
        candles, datetime(2024, 1, 11, 13, 30, tzinfo=UTC)
    )

    assert diagnostic.verdict == "consistent_with_utc+2"


def test_offset_diagnostic_is_inconclusive_for_flat_volume() -> None:
    candles = make_candles(datetime(2024, 1, 11, 8), [1.0] * 12)

    diagnostic = server_offset_volume_diagnostic(
        candles, datetime(2024, 1, 11, 13, 30, tzinfo=UTC)
    )

    assert diagnostic.verdict == "inconclusive"


# ---------------------------------------------------------------------------
# End-to-end on the public demo inputs
# ---------------------------------------------------------------------------


def demo_release() -> HistoricalRelease:
    storage = HistoricalReleaseStorage(DEMO_DIR / "official_releases_allowlist.jsonl")
    return storage.find_by_release_id("us_cpi_2024_01_11")[0]


def run_demo():
    candles = load_mt5_h1_csv(DEMO_DIR / "SYNTHETIC_eurusd_h1_mt5_format.csv")
    return run_event_study(
        demo_release(),
        candles,
        price_data_origin=PriceDataOrigin.SYNTHETIC,
        price_source_description="demo",
        consensus=NO_CONSENSUS,
    )


def test_demo_study_is_deterministic_and_labelled_synthetic() -> None:
    first = run_demo()
    second = run_demo()

    assert first.metrics == second.metrics
    assert first.window.equals(second.window)
    assert first.alignment.minutes_into_event_candle == 30
    assert "SYNTHETIC" in first.price_origin_label
    assert first.limitations[0].startswith("Market data is SYNTHETIC")


# ---------------------------------------------------------------------------
# Consensus surprise
# ---------------------------------------------------------------------------


def test_consensus_unavailable_without_forecasts() -> None:
    status = evaluate_consensus(demo_release(), load_source_registry(REGISTRY_PATH))

    assert not status.available
    assert "no forecast/consensus values" in status.reason


def test_consensus_computed_for_synthetic_demo_forecasts() -> None:
    storage = HistoricalReleaseStorage(DEMO_DIR / "synthetic_releases.jsonl")
    release = storage.find_by_release_id("synthetic_us_cpi_2030_01_15")[0]

    status = evaluate_consensus(release, load_source_registry(REGISTRY_PATH))

    assert status.available
    assert "SYNTHETIC" in status.reason
    assert {s.component_key: s.surprise for s in status.surprises} == {
        "headline_cpi_mom": pytest.approx(0.5),
        "headline_cpi_yoy": pytest.approx(-0.5),
        "core_cpi_mom": pytest.approx(0.0),
    }


def test_consensus_from_restricted_vendor_is_not_used() -> None:
    data = demo_release().model_dump()
    data["forecast_source_name"] = "Vendor"
    data["forecast_source_url"] = "https://www.investing.com/economic-calendar/"
    data["components"][0]["forecast"] = 0.2
    release = HistoricalRelease.model_validate(data)

    status = evaluate_consensus(release, load_source_registry(REGISTRY_PATH))

    assert not status.available
    assert "restricted" in status.reason
