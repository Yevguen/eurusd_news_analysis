"""Single-event EUR/USD H1 event study.

Methodology (also reproduced in every generated report)
=======================================================

Timezone and event timestamp
    The event instant is the release's ``utc_release_time``: the moment the
    publisher lifted its embargo, converted from the official local time
    recorded in the catalogue. All metrics are computed in UTC.

Candle labelling and server offset
    MT5 labels each H1 candle by its OPEN time in the broker-server clock.
    Server time is converted to UTC with ONE fixed offset: the UTC offset
    stored in the release's ``mt5_server_time`` (the catalogue's provisional
    MT5 rule, ``+02:00`` in northern-hemisphere winter). The offset is a
    project assumption, not a verified broker fact. The study refuses windows
    that cross a US or EU daylight-saving transition, because a fixed offset
    cannot be trusted across one.

Alignment rule
    Candle ``k`` covers ``[open_k, open_k + 1 hour)``. The EVENT CANDLE
    (``k = 0``) is the candle whose interval contains the event instant, i.e.
    ``open_0 = floor_to_hour(event_utc)``. A release at hh:00 falls exactly on
    the event candle's open. A release at hh:30 falls inside the event candle,
    which then contains 30 minutes of PRE-release trading; the study reports
    this offset (``minutes_into_event_candle``) instead of hiding it.

Windows (clock hours, contiguous)
    anchor candle    k = -(P + B + 1)       (only supplies a previous close)
    baseline window  k = -(P + B) .. -(P + 1)   B candles
    pre-event window k = -P .. -1               P candles
    event candle     k = 0
    post-event window k = 1 .. M               M candles
    Defaults: P = 6, B = 24, M = 6.

Returns
    Candle log return in basis points: ``r_k = 10_000 * ln(C_k / C_(k-1))``.
    Reference price ``P_ref = C_(-1)``, the close of the last complete candle
    before the event candle. Cumulative return to candle k:
    ``10_000 * ln(C_k / P_ref)``; price change in pips: ``(C_k - P_ref) * 10_000``
    (one EUR/USD pip = 0.0001).

Volatility
    Baseline volatility ``sigma_base`` = sample standard deviation (ddof = 1)
    of ``r_k`` over the baseline window. The event move is standardised as
    ``|r_0| / sigma_base``. Range-based measures compare the event candle's
    high-low range with the mean baseline range. Pre- and post-event realised
    volatility use the same formula over their windows.

Missing candles
    Every candle from the anchor to the end of the post-event window must
    exist. Any gap (including weekend closure) raises
    ``MissingCandlesError`` listing the missing opens; nothing is filled or
    interpolated.

Consensus surprise
    ``actual - forecast`` is computed only when forecasts exist AND come from a
    rights-cleared source; otherwise it is reported as unavailable.

This is a descriptive single-event study. It does not estimate causal effects
and provides no statistical significance across events.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.economic_calendar.historical_models import HistoricalRelease

from .price_data import PRICE_ORIGIN_LABELS, PriceDataOrigin

PIP = 0.0001
BASIS_POINTS = 10_000.0

DST_REFERENCE_ZONES = ("America/New_York", "Europe/Berlin")


class EventStudyError(ValueError):
    """Base class for event-study input problems."""


class MarketDataCoverageError(EventStudyError):
    """Raised when the price data does not cover the requested window."""


class MissingCandlesError(MarketDataCoverageError):
    """Raised when expected H1 candles are absent inside the window."""

    def __init__(self, missing_server_opens: list[datetime]) -> None:
        self.missing_server_opens = missing_server_opens
        shown = ", ".join(
            ts.strftime("%Y-%m-%d %H:%M") for ts in missing_server_opens[:5]
        )
        more = (
            ""
            if len(missing_server_opens) <= 5
            else f" (+{len(missing_server_opens) - 5} more)"
        )
        super().__init__(
            f"{len(missing_server_opens)} expected H1 candle(s) missing "
            f"(server-time opens): {shown}{more}. Missing candles are never "
            "filled; choose another event or smaller windows."
        )


class TimeBasisError(EventStudyError):
    """Raised when a fixed server offset cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class EventWindowSpec:
    """Window lengths, in H1 candles."""

    pre_candles: int = 6
    post_candles: int = 6
    baseline_candles: int = 24

    def __post_init__(self) -> None:
        if self.pre_candles < 2 or self.post_candles < 2:
            raise ValueError("pre_candles and post_candles must be at least 2.")

        if self.baseline_candles < 3:
            raise ValueError("baseline_candles must be at least 3.")

    @property
    def first_relative_index(self) -> int:
        """Relative index of the anchor candle."""

        return -(self.pre_candles + self.baseline_candles + 1)


@dataclass(frozen=True, slots=True)
class EventAlignment:
    """How the event instant maps onto the H1 candle grid."""

    event_time_utc: datetime
    server_utc_offset: timedelta
    event_time_server: datetime
    event_candle_open_utc: datetime
    event_candle_open_server: datetime
    minutes_into_event_candle: int

    @property
    def falls_on_candle_open(self) -> bool:
        return self.minutes_into_event_candle == 0


def floor_to_hour(value: datetime) -> datetime:
    """Truncate a datetime to the start of its hour."""

    return value.replace(minute=0, second=0, microsecond=0)


def align_event(
    event_time_utc: datetime, server_utc_offset: timedelta
) -> EventAlignment:
    """Place an aware UTC instant on the H1 grid of a server clock."""

    if event_time_utc.tzinfo is None or event_time_utc.utcoffset() is None:
        raise TimeBasisError("event_time_utc must be timezone-aware.")

    event_utc = event_time_utc.astimezone(UTC)
    candle_open_utc = floor_to_hour(event_utc)
    event_server = (event_utc + server_utc_offset).replace(tzinfo=None)

    delta = event_utc - candle_open_utc
    minutes = int(delta.total_seconds() // 60)

    return EventAlignment(
        event_time_utc=event_utc,
        server_utc_offset=server_utc_offset,
        event_time_server=event_server,
        event_candle_open_utc=candle_open_utc,
        event_candle_open_server=(candle_open_utc + server_utc_offset).replace(
            tzinfo=None
        ),
        minutes_into_event_candle=minutes,
    )


def server_offset_from_release(release: HistoricalRelease) -> timedelta:
    """Return the (provisional) MT5 server offset recorded for a release."""

    offset = release.mt5_server_time.utcoffset()

    if offset is None:  # pragma: no cover - the model rejects naive times
        raise TimeBasisError("mt5_server_time has no UTC offset.")

    return offset


def dst_transitions_between(start_utc: datetime, end_utc: datetime) -> list[str]:
    """List reference zones whose UTC offset changes inside the interval."""

    changed: list[str] = []

    for zone_name in DST_REFERENCE_ZONES:
        zone = ZoneInfo(zone_name)

        if (
            start_utc.astimezone(zone).utcoffset()
            != end_utc.astimezone(zone).utcoffset()
        ):
            changed.append(zone_name)

    return changed


def zones_in_daylight_saving(instant_utc: datetime) -> list[str]:
    """List reference zones observing daylight-saving time at an instant."""

    return [
        zone_name
        for zone_name in DST_REFERENCE_ZONES
        if (instant_utc.astimezone(ZoneInfo(zone_name)).dst() or timedelta(0))
        != timedelta(0)
    ]


def extract_window(
    candles: pd.DataFrame,
    alignment: EventAlignment,
    spec: EventWindowSpec,
) -> pd.DataFrame:
    """Return the contiguous candles from the anchor to the last post candle.

    ``candles`` must come from ``load_mt5_h1_csv`` (naive server-time opens).
    """

    first = spec.first_relative_index
    last = spec.post_candles
    one_hour = timedelta(hours=1)

    expected = [
        alignment.event_candle_open_server + one_hour * k
        for k in range(first, last + 1)
    ]

    if candles.empty:
        raise MarketDataCoverageError("The price series is empty.")

    data_start = candles["server_open_time"].iloc[0].to_pydatetime()
    data_end = candles["server_open_time"].iloc[-1].to_pydatetime()

    if expected[0] < data_start or expected[-1] > data_end:
        raise MarketDataCoverageError(
            "Price data does not cover the event window: needs server-time "
            f"{expected[0]:%Y-%m-%d %H:%M} to {expected[-1]:%Y-%m-%d %H:%M}, "
            f"data covers {data_start:%Y-%m-%d %H:%M} to {data_end:%Y-%m-%d %H:%M}."
        )

    indexed = candles.set_index("server_open_time")
    expected_index = pd.DatetimeIndex(expected)
    present = expected_index.isin(indexed.index)

    if not present.all():
        raise MissingCandlesError(
            [ts.to_pydatetime() for ts in expected_index[~present]]
        )

    window = indexed.loc[expected_index].reset_index()
    window = window.rename(columns={"index": "server_open_time"})
    window.insert(0, "relative_index", list(range(first, last + 1)))
    window.insert(
        2,
        "open_time_utc",
        [
            (ts.to_pydatetime() - alignment.server_utc_offset).replace(tzinfo=UTC)
            for ts in window["server_open_time"]
        ],
    )

    return window


def _log_bp(numerator: float, denominator: float) -> float:
    return BASIS_POINTS * math.log(numerator / denominator)


def _sample_std(values: list[float]) -> float:
    return float(pd.Series(values, dtype="float64").std(ddof=1))


@dataclass(frozen=True, slots=True)
class OffsetDiagnosticRow:
    """Tick-volume check of one candidate MT5 server offset."""

    utc_offset_hours: int
    candidate_candle_open_server: datetime
    tick_volume: int | None
    previous_tick_volume: int | None
    jump_ratio: float | None


@dataclass(frozen=True, slots=True)
class OffsetDiagnostic:
    """Heuristic evidence about the MT5 server offset around one event."""

    rows: list[OffsetDiagnosticRow]
    verdict: str
    explanation: str


def server_offset_volume_diagnostic(
    candles: pd.DataFrame,
    event_time_utc: datetime,
    *,
    candidate_offsets_hours: tuple[int, ...] = (0, 1, 2, 3),
    min_ratio: float = 2.0,
    min_separation: float = 2.0,
) -> OffsetDiagnostic:
    """Compare tick-volume jumps under alternative server offsets.

    For each candidate offset ``h`` the candle that would contain the event
    is ``floor(event_utc + h)`` in server time. A scheduled high-impact
    release usually lifts tick volume sharply versus the preceding candle.
    The verdict names an offset only when its jump ratio is at least
    ``min_ratio`` and ``min_separation`` times the next best ratio;
    otherwise it is ``inconclusive``. This is circumstantial evidence, never
    proof of the broker's clock.
    """

    by_time = candles.set_index("server_open_time")["tick_volume"]
    rows: list[OffsetDiagnosticRow] = []

    for hours in candidate_offsets_hours:
        alignment = align_event(event_time_utc, timedelta(hours=hours))
        candle_open = alignment.event_candle_open_server
        previous_open = candle_open - timedelta(hours=1)

        volume = by_time.get(pd.Timestamp(candle_open))
        previous = by_time.get(pd.Timestamp(previous_open))

        ratio = (
            float(volume) / float(previous)
            if volume is not None and previous not in (None, 0)
            else None
        )

        rows.append(
            OffsetDiagnosticRow(
                utc_offset_hours=hours,
                candidate_candle_open_server=candle_open,
                tick_volume=None if volume is None else int(volume),
                previous_tick_volume=None if previous is None else int(previous),
                jump_ratio=ratio,
            )
        )

    ranked = sorted(
        (row for row in rows if row.jump_ratio is not None),
        key=lambda row: row.jump_ratio or 0.0,
        reverse=True,
    )

    if not ranked:
        return OffsetDiagnostic(rows, "inconclusive", "No candidate candle was found.")

    best = ranked[0]
    runner_up = ranked[1].jump_ratio if len(ranked) > 1 else None
    best_ratio = best.jump_ratio or 0.0

    if best_ratio >= min_ratio and (
        runner_up is None or best_ratio >= min_separation * runner_up
    ):
        sign = "+" if best.utc_offset_hours >= 0 else "-"
        return OffsetDiagnostic(
            rows,
            f"consistent_with_utc{sign}{abs(best.utc_offset_hours)}",
            (
                f"Under UTC{sign}{abs(best.utc_offset_hours)} the event candle's tick "
                f"volume is {best_ratio:.2f}x the preceding candle, clearly above "
                "the other candidates. Circumstantial evidence only."
            ),
        )

    return OffsetDiagnostic(
        rows,
        "inconclusive",
        (
            "No candidate offset shows a clearly dominant tick-volume jump "
            f"(best ratio {best_ratio:.2f}x). The offset remains an assumption."
        ),
    )


@dataclass(frozen=True, slots=True)
class ConsensusSurprise:
    """Actual-minus-forecast surprise for one numeric component."""

    component_key: str
    actual: float
    forecast: float
    surprise: float
    unit: str | None


@dataclass(frozen=True, slots=True)
class ConsensusStatus:
    """Whether a consensus surprise could be computed, and why."""

    available: bool
    reason: str
    surprises: list[ConsensusSurprise] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    """Complete output of one single-event study."""

    release: HistoricalRelease
    price_data_origin: PriceDataOrigin
    price_source_description: str
    spec: EventWindowSpec
    alignment: EventAlignment
    window: pd.DataFrame
    metrics: dict[str, float | int | None]
    offset_diagnostic: OffsetDiagnostic
    consensus: ConsensusStatus
    limitations: list[str]

    @property
    def price_origin_label(self) -> str:
        return PRICE_ORIGIN_LABELS[self.price_data_origin]


def report_horizons(spec: EventWindowSpec) -> list[int]:
    """Post-event horizons (relative candle indices) reported as metrics."""

    return sorted(h for h in {0, 1, 3, spec.post_candles} if h <= spec.post_candles)


def compute_metrics(
    window: pd.DataFrame, spec: EventWindowSpec
) -> dict[str, float | int | None]:
    """Compute return and volatility metrics for an extracted window."""

    closes = dict(zip(window["relative_index"], window["close"], strict=True))
    opens = dict(zip(window["relative_index"], window["open"], strict=True))
    highs = dict(zip(window["relative_index"], window["high"], strict=True))
    lows = dict(zip(window["relative_index"], window["low"], strict=True))
    volumes = dict(zip(window["relative_index"], window["tick_volume"], strict=True))

    def candle_return(k: int) -> float:
        return _log_bp(closes[k], closes[k - 1])

    def candle_range_pips(k: int) -> float:
        return (highs[k] - lows[k]) / PIP

    baseline = range(-(spec.pre_candles + spec.baseline_candles), -spec.pre_candles)
    pre = range(-spec.pre_candles, 0)
    post = range(1, spec.post_candles + 1)

    reference = closes[-1]
    baseline_returns = [candle_return(k) for k in baseline]
    baseline_sigma = _sample_std(baseline_returns)
    baseline_mean_range = sum(candle_range_pips(k) for k in baseline) / len(baseline)
    baseline_volumes = sorted(volumes[k] for k in baseline)
    baseline_median_volume = float(pd.Series(baseline_volumes).median())

    event_return = candle_return(0)
    event_range = candle_range_pips(0)

    metrics: dict[str, float | int | None] = {
        "reference_close": reference,
        "event_candle_open": opens[0],
        "event_candle_high": highs[0],
        "event_candle_low": lows[0],
        "event_candle_close": closes[0],
        "event_candle_return_bp": event_return,
        "event_candle_range_pips": event_range,
        "event_candle_tick_volume": int(volumes[0]),
        "pre_event_drift_bp": _log_bp(closes[-1], opens[-spec.pre_candles]),
        "baseline_volatility_bp": baseline_sigma,
        "baseline_mean_range_pips": baseline_mean_range,
        "baseline_median_tick_volume": baseline_median_volume,
        "pre_event_realized_volatility_bp": _sample_std(
            [candle_return(k) for k in pre]
        ),
        "post_event_realized_volatility_bp": _sample_std(
            [candle_return(k) for k in post]
        ),
        "event_abs_return_in_baseline_sigmas": (
            abs(event_return) / baseline_sigma if baseline_sigma > 0 else None
        ),
        "event_range_vs_baseline_mean_range": (
            event_range / baseline_mean_range if baseline_mean_range > 0 else None
        ),
        "event_tick_volume_vs_baseline_median": (
            volumes[0] / baseline_median_volume if baseline_median_volume > 0 else None
        ),
    }

    for horizon in report_horizons(spec):
        metrics[f"cumulative_return_bp_to_close_k{horizon}"] = _log_bp(
            closes[horizon], reference
        )
        metrics[f"price_change_pips_to_close_k{horizon}"] = (
            closes[horizon] - reference
        ) / PIP

    return metrics


def add_path_columns(window: pd.DataFrame) -> pd.DataFrame:
    """Add per-candle return and cumulative-path columns."""

    enriched = window.copy()
    reference = float(enriched.loc[enriched["relative_index"] == -1, "close"].iloc[0])
    previous_close = enriched["close"].shift(1)

    enriched["log_return_bp"] = BASIS_POINTS * (
        (enriched["close"] / previous_close).map(math.log, na_action="ignore")
    )
    enriched["cumulative_return_bp"] = BASIS_POINTS * (
        (enriched["close"] / reference).map(math.log)
    )
    enriched["pips_from_reference"] = (enriched["close"] - reference) / PIP

    return enriched


def run_event_study(
    release: HistoricalRelease,
    candles: pd.DataFrame,
    *,
    price_data_origin: PriceDataOrigin,
    price_source_description: str,
    consensus: ConsensusStatus,
    spec: EventWindowSpec | None = None,
) -> EventStudyResult:
    """Align one release with H1 candles and compute the event study."""

    window_spec = spec or EventWindowSpec()
    server_offset = server_offset_from_release(release)
    alignment = align_event(release.utc_release_time, server_offset)

    window_start_utc = alignment.event_candle_open_utc + timedelta(
        hours=window_spec.first_relative_index
    )
    window_end_utc = alignment.event_candle_open_utc + timedelta(
        hours=window_spec.post_candles + 1
    )

    crossing = dst_transitions_between(window_start_utc, window_end_utc)

    if crossing:
        raise TimeBasisError(
            "The event window crosses a daylight-saving transition in "
            f"{', '.join(crossing)}; a single fixed MT5 server offset cannot be "
            "applied safely. Use a window that avoids the transition."
        )

    window = add_path_columns(extract_window(candles, alignment, window_spec))
    metrics = compute_metrics(window, window_spec)
    diagnostic = server_offset_volume_diagnostic(candles, release.utc_release_time)

    offset_hours = server_offset.total_seconds() / 3600
    limitations = build_limitations(
        release=release,
        alignment=alignment,
        price_data_origin=price_data_origin,
        consensus=consensus,
        diagnostic=diagnostic,
        offset_hours=offset_hours,
    )

    return EventStudyResult(
        release=release,
        price_data_origin=price_data_origin,
        price_source_description=price_source_description,
        spec=window_spec,
        alignment=alignment,
        window=window,
        metrics=metrics,
        offset_diagnostic=diagnostic,
        consensus=consensus,
        limitations=limitations,
    )


def build_limitations(
    *,
    release: HistoricalRelease,
    alignment: EventAlignment,
    price_data_origin: PriceDataOrigin,
    consensus: ConsensusStatus,
    diagnostic: OffsetDiagnostic,
    offset_hours: float,
) -> list[str]:
    """Return the limitations that apply to one study, most important first."""

    items: list[str] = []

    if price_data_origin == PriceDataOrigin.SYNTHETIC:
        items.append(
            "Market data is SYNTHETIC. Every price-based number in this report "
            "is a pipeline demonstration and says nothing about how EUR/USD "
            "actually reacted."
        )
    elif price_data_origin == PriceDataOrigin.AUTHENTIC_PRIVATE:
        items.append(
            "Market data is authentic but private (broker MT5 export); the "
            "report must not be redistributed with the candle data."
        )

    sign = "+" if offset_hours >= 0 else "-"
    items.append(
        f"The MT5 server offset UTC{sign}{abs(offset_hours):g} is the catalogue's "
        "provisional assumption, not a verified broker fact; tick-volume "
        f"diagnostic verdict: {diagnostic.verdict}."
    )

    dst_zones = zones_in_daylight_saving(alignment.event_time_utc)

    if dst_zones and offset_hours == 2:
        items.append(
            "The event falls in a daylight-saving period "
            f"({', '.join(dst_zones)}) while the recorded offset is the winter "
            "value +02:00; the common broker summer convention would be +03:00."
        )

    if not alignment.falls_on_candle_open:
        items.append(
            f"The release occurred {alignment.minutes_into_event_candle} minutes "
            "after the event candle opened, so the event-candle return also "
            "contains pre-release trading. H1 data cannot isolate the first "
            "minutes after the release."
        )

    if not consensus.available:
        items.append(f"Consensus-surprise analysis unavailable: {consensus.reason}")

    items.append(
        "Single-event, descriptive study: no control for concurrent news, no "
        "cross-event statistics and no causal claim."
    )

    if release.data_origin is None:
        items.append("The release record does not declare its data_origin.")

    return items


def _candle_record(row: dict[Any, Any]) -> dict[str, Any]:
    """Convert one enriched window row into JSON-compatible values."""

    log_return = row["log_return_bp"]

    return {
        "relative_index": int(row["relative_index"]),
        "open_time_utc": row["open_time_utc"].isoformat(),
        "open_time_server": row["server_open_time"].isoformat(),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "tick_volume": int(row["tick_volume"]),
        "log_return_bp": None if pd.isna(log_return) else float(log_return),
        "cumulative_return_bp": float(row["cumulative_return_bp"]),
        "pips_from_reference": float(row["pips_from_reference"]),
    }


def result_to_serialisable(result: EventStudyResult) -> dict[str, Any]:
    """Convert a result into plain JSON-compatible structures (unrounded)."""

    release = result.release
    alignment = result.alignment

    return {
        "event": {
            "release_id": release.release_id,
            "event_key": release.event_key,
            "reference_period": release.reference_period,
            "release_data_origin": (
                release.data_origin.value if release.data_origin else None
            ),
            "official_source_name": release.official_source_name,
            "official_source_url": release.official_source_url,
            "official_release_time": release.official_release_time.isoformat(),
            "utc_release_time": release.utc_release_time.isoformat(),
            "mt5_server_time": release.mt5_server_time.isoformat(),
        },
        "market_data": {
            "data_origin": result.price_data_origin.value,
            "label": result.price_origin_label,
            "source_description": result.price_source_description,
            "timeframe": "H1",
            "time_basis": "mt5_server_time converted to UTC with a fixed offset",
        },
        "alignment": {
            "server_utc_offset_hours": alignment.server_utc_offset.total_seconds()
            / 3600,
            "event_time_utc": alignment.event_time_utc.isoformat(),
            "event_time_server": alignment.event_time_server.isoformat(),
            "event_candle_open_utc": alignment.event_candle_open_utc.isoformat(),
            "event_candle_open_server": alignment.event_candle_open_server.isoformat(),
            "minutes_into_event_candle": alignment.minutes_into_event_candle,
        },
        "window_spec": {
            "pre_candles": result.spec.pre_candles,
            "post_candles": result.spec.post_candles,
            "baseline_candles": result.spec.baseline_candles,
            "anchor_relative_index": result.spec.first_relative_index,
        },
        "metrics": dict(result.metrics),
        "offset_diagnostic": {
            "verdict": result.offset_diagnostic.verdict,
            "explanation": result.offset_diagnostic.explanation,
            "rows": [
                {
                    "utc_offset_hours": row.utc_offset_hours,
                    "candidate_candle_open_server": (
                        row.candidate_candle_open_server.isoformat()
                    ),
                    "tick_volume": row.tick_volume,
                    "previous_tick_volume": row.previous_tick_volume,
                    "jump_ratio": row.jump_ratio,
                }
                for row in result.offset_diagnostic.rows
            ],
        },
        "consensus": {
            "available": result.consensus.available,
            "reason": result.consensus.reason,
            "surprises": [
                {
                    "component_key": item.component_key,
                    "actual": item.actual,
                    "forecast": item.forecast,
                    "surprise": item.surprise,
                    "unit": item.unit,
                }
                for item in result.consensus.surprises
            ],
        },
        "candles": [_candle_record(row) for row in result.window.to_dict("records")],
        "limitations": list(result.limitations),
    }
