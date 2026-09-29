"""Deterministic SYNTHETIC demonstration data for the public repository.

Nothing in this module describes real economic publications or real market
prices. The records and candles exist only so that the public repository can
exercise its models, validation, persistence, Parquet export and event-study
pipeline without redistributing third-party data.

Safeguards that keep the data unmistakably synthetic:

- every release uses ``data_origin="synthetic"`` and a ``synthetic_`` ID prefix
  (enforced by ``HistoricalRelease``);
- releases are dated in January 2030, outside any historical research slice;
- values are round placeholders, not plausible statistics;
- source names say "SYNTHETIC" and URLs use the reserved ``example.com`` domain;
- the candle series starts at exactly 1.00000, far from real EUR/USD levels in
  January 2024, and contains NO injected event effect: it is pure noise.

The candle generator uses only ``random.Random.random()`` and additions
(Irwin-Hall approximation of a normal draw), so output is reproducible across
platforms and Python versions.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from src.economic_calendar.historical_models import (
    ComponentValueType,
    DataOrigin,
    HistoricalRelease,
    HistoricalReleaseComponent,
)
from src.economic_calendar.timestamps import derive_release_timestamps

US_EASTERN_WINTER = timezone(timedelta(hours=-5), name="EST")
EUROPE_CENTRAL_WINTER = timezone(timedelta(hours=1), name="CET")

SYNTHETIC_SOURCE_NAME = "SYNTHETIC demonstration source (not real data)"
SYNTHETIC_FORECAST_SOURCE_NAME = "SYNTHETIC consensus source (not real data)"
SYNTHETIC_URL_ROOT = "https://example.com/synthetic"

SYNTHETIC_NOTE = (
    "SYNTHETIC record generated for the public demonstration. It does not "
    "describe any real publication and must not be used as a historical "
    "observation."
)

# ---------------------------------------------------------------------------
# Synthetic historical releases
# ---------------------------------------------------------------------------


def _numeric(
    key: str,
    name: str,
    actual: float,
    previous: float,
    unit: str,
    forecast: float | None = None,
) -> HistoricalReleaseComponent:
    return HistoricalReleaseComponent(
        component_key=key,
        component_name=name,
        value_type=ComponentValueType.NUMERIC,
        actual=actual,
        forecast=forecast,
        previous=previous,
        unit=unit,
    )


def _text(key: str, name: str, actual: str) -> HistoricalReleaseComponent:
    return HistoricalReleaseComponent(
        component_key=key,
        component_name=name,
        value_type=ComponentValueType.TEXT,
        actual=actual,
        unit=None,
    )


def _release(
    *,
    release_id: str,
    event_key: str,
    official_release_time: datetime,
    reference_period: str | None,
    release_summary: str | None,
    components: list[HistoricalReleaseComponent],
    release_group_id: str | None = None,
    geography_key: str | None = None,
    geography_name: str | None = None,
    with_forecast_source: bool = False,
) -> HistoricalRelease:
    timestamps = derive_release_timestamps(official_release_time)

    return HistoricalRelease(
        release_id=release_id,
        event_key=event_key,
        release_group_id=release_group_id,
        geography_key=geography_key,
        geography_name=geography_name,
        reference_period=reference_period,
        official_release_time=timestamps.official_release_time,
        utc_release_time=timestamps.utc_release_time,
        mt5_server_time=timestamps.mt5_server_time,
        official_source_name=SYNTHETIC_SOURCE_NAME,
        official_source_url=f"{SYNTHETIC_URL_ROOT}/{release_id}",
        forecast_source_name=(
            SYNTHETIC_FORECAST_SOURCE_NAME if with_forecast_source else None
        ),
        forecast_source_url=(
            f"{SYNTHETIC_URL_ROOT}/consensus/{release_id}"
            if with_forecast_source
            else None
        ),
        release_summary=release_summary,
        components=components,
        notes=SYNTHETIC_NOTE,
        data_origin=DataOrigin.SYNTHETIC,
    )


def build_synthetic_releases() -> list[HistoricalRelease]:
    """Return the SYNTHETIC demonstration catalogue, in publication order."""

    state_group_id = "eur_germany_state_cpi_2030_01_29_synthetic"

    return [
        _release(
            release_id="synthetic_us_cpi_2030_01_15",
            event_key="us_cpi",
            official_release_time=datetime(
                2030, 1, 15, 8, 30, tzinfo=US_EASTERN_WINTER
            ),
            reference_period="2029-12",
            release_summary="SYNTHETIC multi-component numeric release.",
            components=[
                _numeric(
                    "headline_cpi_mom",
                    "Headline CPI (MoM)",
                    1.0,
                    0.5,
                    "percent month-over-month",
                    forecast=0.5,
                ),
                _numeric(
                    "headline_cpi_yoy",
                    "Headline CPI (YoY)",
                    2.0,
                    1.5,
                    "percent year-over-year",
                    forecast=2.5,
                ),
                _numeric(
                    "core_cpi_mom",
                    "Core CPI (MoM)",
                    3.0,
                    2.5,
                    "percent month-over-month",
                    forecast=3.0,
                ),
                _numeric(
                    "core_cpi_yoy",
                    "Core CPI (YoY)",
                    4.0,
                    3.5,
                    "percent year-over-year",
                ),
            ],
            with_forecast_source=True,
        ),
        _release(
            release_id="synthetic_eur_ecb_president_press_conference_2030_01_24",
            event_key="eur_ecb_president_press_conference",
            official_release_time=datetime(
                2030, 1, 24, 14, 45, tzinfo=EUROPE_CENTRAL_WINTER
            ),
            reference_period=None,
            release_summary=(
                "SYNTHETIC summary-only release: placeholder text, not a "
                "description of any real press conference."
            ),
            components=[],
        ),
        _release(
            release_id="synthetic_eur_germany_state_cpi_state_a_2030_01_29",
            event_key="eur_germany_state_cpi",
            official_release_time=datetime(
                2030, 1, 29, 10, 0, tzinfo=EUROPE_CENTRAL_WINTER
            ),
            reference_period="2030-01",
            release_summary="SYNTHETIC state CPI release (group member A).",
            components=[
                _numeric(
                    "state_headline_cpi_mom",
                    "State headline CPI (MoM)",
                    1.0,
                    0.0,
                    "percent month-over-month",
                ),
                _numeric(
                    "state_headline_cpi_yoy",
                    "State headline CPI (YoY)",
                    2.0,
                    1.0,
                    "percent year-over-year",
                ),
            ],
            release_group_id=state_group_id,
            geography_key="synthetic_state_a",
            geography_name="Synthetic State A",
        ),
        _release(
            release_id="synthetic_eur_germany_state_cpi_state_b_2030_01_29",
            event_key="eur_germany_state_cpi",
            official_release_time=datetime(
                2030, 1, 29, 10, 0, tzinfo=EUROPE_CENTRAL_WINTER
            ),
            reference_period="2030-01",
            release_summary="SYNTHETIC state CPI release (group member B).",
            components=[
                _numeric(
                    "state_headline_cpi_mom",
                    "State headline CPI (MoM)",
                    -1.0,
                    0.0,
                    "percent month-over-month",
                ),
                _numeric(
                    "state_headline_cpi_yoy",
                    "State headline CPI (YoY)",
                    1.0,
                    2.0,
                    "percent year-over-year",
                ),
            ],
            release_group_id=state_group_id,
            geography_key="synthetic_state_b",
            geography_name="Synthetic State B",
        ),
        _release(
            release_id="synthetic_us_fomc_decision_statement_2030_01_30",
            event_key="us_fomc_decision_statement",
            official_release_time=datetime(
                2030, 1, 30, 14, 0, tzinfo=US_EASTERN_WINTER
            ),
            reference_period="2030-01-29_to_2030-01-30",
            release_summary="SYNTHETIC text-component release.",
            components=[
                _text(
                    "federal_funds_target_range",
                    "Federal funds target range",
                    "SYNTHETIC placeholder range (not a real decision).",
                ),
                _text(
                    "policy_statement",
                    "Policy statement",
                    "SYNTHETIC placeholder statement (not real policy text).",
                ),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Synthetic EUR/USD H1 candles in MetaTrader 5 export format
# ---------------------------------------------------------------------------

SYNTHETIC_PRICE_SEED = 20240111
SYNTHETIC_PRICE_START_LEVEL = 1.0
SYNTHETIC_PRICE_FIRST_DAY = date(2024, 1, 2)
SYNTHETIC_PRICE_LAST_DAY = date(2024, 1, 12)

# Hourly close-to-close step scale and wick scale, in price units.
_STEP_SCALE = 0.0007
_WICK_SCALE = 0.0003

MT5_CSV_HEADER = (
    "<DATE>",
    "<TIME>",
    "<OPEN>",
    "<HIGH>",
    "<LOW>",
    "<CLOSE>",
    "<TICKVOL>",
    "<VOL>",
    "<SPREAD>",
)


@dataclass(frozen=True, slots=True)
class SyntheticCandle:
    """One SYNTHETIC H1 candle labelled in MT5 server time (candle open)."""

    server_open_time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int


def _standard_normal_draw(generator: random.Random) -> float:
    """Irwin-Hall approximation of N(0, 1): sum of 12 uniforms minus 6."""

    return sum(generator.random() for _ in range(12)) - 6.0


def _weekday_server_hours(first_day: date, last_day: date) -> Iterator[datetime]:
    current = first_day

    while current <= last_day:
        if current.weekday() < 5:
            for hour in range(24):
                yield datetime.combine(current, time(hour=hour))

        current += timedelta(days=1)


def build_synthetic_candles() -> list[SyntheticCandle]:
    """Return SYNTHETIC weekday H1 candles for 2024-01-02..2024-01-12.

    Timestamps are naive MT5 server times, exactly as an MT5 export labels
    them. Weekends are absent, as in real FX data.
    """

    generator = random.Random(SYNTHETIC_PRICE_SEED)
    candles: list[SyntheticCandle] = []
    previous_close = round(SYNTHETIC_PRICE_START_LEVEL, 5)

    for server_open_time in _weekday_server_hours(
        SYNTHETIC_PRICE_FIRST_DAY,
        SYNTHETIC_PRICE_LAST_DAY,
    ):
        open_price = previous_close
        close_price = round(
            open_price + _STEP_SCALE * _standard_normal_draw(generator),
            5,
        )
        upper_wick = abs(_WICK_SCALE * _standard_normal_draw(generator))
        lower_wick = abs(_WICK_SCALE * _standard_normal_draw(generator))

        candles.append(
            SyntheticCandle(
                server_open_time=server_open_time,
                open=open_price,
                high=round(max(open_price, close_price) + upper_wick, 5),
                low=round(min(open_price, close_price) - lower_wick, 5),
                close=close_price,
                tick_volume=800 + int(generator.random() * 400),
                spread=1,
            )
        )
        previous_close = close_price

    return candles


def render_mt5_csv(candles: list[SyntheticCandle]) -> str:
    """Render candles as tab-separated text in MT5 export layout."""

    lines = ["\t".join(MT5_CSV_HEADER)]

    for candle in candles:
        lines.append(
            "\t".join(
                [
                    candle.server_open_time.strftime("%Y.%m.%d"),
                    candle.server_open_time.strftime("%H:%M:%S"),
                    f"{candle.open:.5f}",
                    f"{candle.high:.5f}",
                    f"{candle.low:.5f}",
                    f"{candle.close:.5f}",
                    str(candle.tick_volume),
                    "0",
                    str(candle.spread),
                ]
            )
        )

    return "\n".join(lines) + "\n"


def render_releases_jsonl(releases: list[HistoricalRelease]) -> str:
    """Render releases in the same JSONL layout used by the storage layer."""

    return "".join(f"{release.model_dump_json()}\n" for release in releases)
