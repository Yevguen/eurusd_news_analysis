"""Write event-study outputs: JSON (machine-readable), Markdown and a PNG chart.

Outputs are deterministic for identical inputs: no wall-clock timestamps are
embedded, floats are rounded to fixed precision and JSON keys are sorted.
File names carry the price-data origin so that a synthetic demonstration can
never be mistaken for an analysis of real prices.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from src.impact_analysis.event_study import (  # noqa: E402
    EventStudyResult,
    report_horizons,
    result_to_serialisable,
)
from src.impact_analysis.price_data import PriceDataOrigin  # noqa: E402

REPORT_SCHEMA_VERSION = 1
FLOAT_DECIMALS = 6

# Chart tokens (validated reference palette, light surface).
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"


@dataclass(frozen=True, slots=True)
class ReportPaths:
    """Locations of the files written for one study."""

    json_path: Path
    markdown_path: Path
    chart_path: Path


def output_stem(result: EventStudyResult) -> str:
    """Return the file stem, e.g. ``us_cpi_2024_01_11__synthetic_prices``."""

    return f"{result.release.release_id}__{result.price_data_origin.value}_prices"


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, FLOAT_DECIMALS)
        return 0.0 if rounded == 0 else rounded

    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_round_floats(item) for item in value]

    return value


def build_report_payload(
    result: EventStudyResult,
    *,
    source_attribution: str | None,
) -> dict[str, Any]:
    """Return the JSON document for one study."""

    payload = result_to_serialisable(result)
    payload["schema_version"] = REPORT_SCHEMA_VERSION
    payload["event"]["source_attribution"] = source_attribution
    payload["generated_by"] = "scripts/generate_eurusd_report.py"
    payload["disclaimer"] = (
        "Descriptive single-event study; not investment advice. Code is MIT "
        "licensed; third-party data remains subject to its own terms "
        "(see DATA_SOURCES.md)."
    )

    return _round_floats(payload)


def write_json(payload: dict[str, Any], path: Path) -> None:
    """Write sorted, indented JSON with LF line endings."""

    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        file.write("\n")


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def _chart_title(result: EventStudyResult) -> str:
    event_time = result.alignment.event_time_utc

    return (
        f"EUR/USD H1 around {result.release.release_id} - "
        f"release {event_time:%d %b %Y, %H:%M} UTC"
    )


def write_chart(result: EventStudyResult, path: Path) -> None:
    """Plot the price path in pips from the pre-event reference close."""

    window = result.window
    visible = window[window["relative_index"] >= -result.spec.pre_candles]
    one_hour = timedelta(hours=1)
    half_hour = timedelta(minutes=30)

    close_times = [ts + one_hour for ts in visible["open_time_utc"]]
    mid_times = [ts + half_hour for ts in visible["open_time_utc"]]
    reference = float(result.metrics["reference_close"] or 0.0)
    highs = (visible["high"] - reference) / 0.0001
    lows = (visible["low"] - reference) / 0.0001

    figure, axis = plt.subplots(figsize=(10, 5.4), dpi=150)
    figure.patch.set_facecolor(SURFACE)
    axis.set_facecolor(SURFACE)

    event_open = result.alignment.event_candle_open_utc
    axis.axvspan(
        float(mdates.date2num(event_open)),
        float(mdates.date2num(event_open + one_hour)),
        color=SERIES,
        alpha=0.08,
        lw=0,
    )
    axis.axhline(0, color=BASELINE, linewidth=1)

    axis.vlines(mid_times, lows, highs, color=BASELINE, linewidth=1.5, zorder=2)

    axis.plot(
        close_times,
        visible["pips_from_reference"].tolist(),
        color=SERIES,
        linewidth=2,
        solid_joinstyle="round",
        solid_capstyle="round",
        marker="o",
        markersize=6,
        markerfacecolor=SERIES,
        markeredgecolor=SURFACE,
        markeredgewidth=2,
        zorder=3,
    )

    event_time = result.alignment.event_time_utc
    axis.axvline(
        float(mdates.date2num(event_time)),
        color=TEXT_SECONDARY,
        linewidth=1,
        zorder=1,
    )
    axis.annotate(
        f"Release {event_time:%H:%M} UTC",
        xy=(event_time, 1.0),
        xycoords=("data", "axes fraction"),
        xytext=(4, -4),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=9,
        color=TEXT_SECONDARY,
    )

    for horizon in (0, result.spec.post_candles):
        row = visible[visible["relative_index"] == horizon].iloc[0]
        value = float(row["pips_from_reference"])
        axis.annotate(
            f"k={horizon}: {value:+.1f} pips",
            xy=(row["open_time_utc"] + one_hour, value),
            xytext=(6, 8 if value >= 0 else -14),
            textcoords="offset points",
            fontsize=9,
            color=TEXT_PRIMARY,
        )

    axis.set_ylabel("Pips from pre-event reference close", color=TEXT_SECONDARY)
    axis.set_xlabel(
        f"{result.alignment.event_time_utc:%d %b %Y}, UTC "
        "(points at candle closes; grey bars: candle high-low)",
        color=TEXT_SECONDARY,
    )
    axis.grid(axis="y", color=GRIDLINE, linewidth=1)
    axis.set_axisbelow(True)
    axis.tick_params(colors=TEXT_MUTED, labelsize=9)

    for side in ("top", "right"):
        axis.spines[side].set_visible(False)

    for side in ("left", "bottom"):
        axis.spines[side].set_color(BASELINE)

    axis.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))

    figure.suptitle(
        _chart_title(result), x=0.01, ha="left", fontsize=12, color=TEXT_PRIMARY
    )
    axis.set_title(
        f"Market data: {result.price_origin_label}",
        loc="left",
        fontsize=9.5,
        color=TEXT_PRIMARY,
        fontweight="bold",
    )

    if result.price_data_origin == PriceDataOrigin.SYNTHETIC:
        axis.text(
            0.5,
            0.5,
            "SYNTHETIC",
            transform=axis.transAxes,
            ha="center",
            va="center",
            fontsize=64,
            color=TEXT_MUTED,
            alpha=0.12,
            rotation=20,
            zorder=0,
        )

    figure.tight_layout()
    figure.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(figure)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "n/a"

    if isinstance(value, float):
        return f"{value:,.{decimals}f}"

    return str(value)


def _signed(value: Any, decimals: int = 2) -> str:
    return "n/a" if value is None else f"{value:+,.{decimals}f}"


def build_markdown(
    result: EventStudyResult,
    payload: dict[str, Any],
    *,
    chart_file_name: str,
) -> str:
    """Return the human-readable report."""

    release = result.release
    alignment = result.alignment
    metrics = result.metrics
    spec = result.spec
    release_origin = release.data_origin.value if release.data_origin else "undeclared"
    attribution = payload["event"].get("source_attribution")
    offset = payload["alignment"]["server_utc_offset_hours"]

    lines: list[str] = [
        f"# EUR/USD H1 event study - `{release.release_id}`",
        "",
        "> **DATA ORIGIN**",
        f"> - Event record: **{release_origin.upper()}** "
        f"({release.official_source_name})",
        f"> - Market data: **{result.price_origin_label}**",
        f"> - Price source: {result.price_source_description}",
        "",
    ]

    if result.price_data_origin == PriceDataOrigin.SYNTHETIC:
        lines += [
            "> The price series is synthetic noise with no injected event effect. "
            "The numbers below demonstrate the pipeline only and must not be read "
            "as EUR/USD market behaviour.",
            "",
        ]

    lines += [
        "## Event",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Release ID | `{release.release_id}` |",
        f"| Event rule | `{release.event_key}` |",
        f"| Reference period | {release.reference_period or 'n/a'} |",
        f"| Official source | [{release.official_source_name}]({release.official_source_url}) |",
        f"| Official release time | {release.official_release_time.isoformat()} |",
        f"| UTC release time | {release.utc_release_time.isoformat()} |",
        f"| MT5 server time (provisional) | {release.mt5_server_time.isoformat()} |",
        "",
    ]

    numeric = [c for c in release.components if c.value_type.value == "numeric"]

    if numeric:
        lines += [
            "| Component | Actual | Previous | Forecast | Unit |",
            "|---|---:|---:|---:|---|",
        ]
        lines += [
            f"| {c.component_name} | {c.actual} | "
            f"{c.previous if c.previous is not None else 'n/a'} | "
            f"{c.forecast if c.forecast is not None else 'n/a'} | {c.unit} |"
            for c in numeric
        ]
        lines.append("")

    lines += [
        "## Timestamp provenance and candle alignment",
        "",
        f"- The event instant is the official release time converted to UTC: "
        f"**{alignment.event_time_utc:%Y-%m-%d %H:%M} UTC**.",
        f"- MT5 candles are labelled in broker-server time; the study converts "
        f"them with a fixed offset of **UTC{offset:+g}** taken from the release "
        "record's provisional `mt5_server_time` (not a verified broker fact).",
        f"- Event candle (k = 0): opens {alignment.event_candle_open_utc:%Y-%m-%d %H:%M} "
        f"UTC = {alignment.event_candle_open_server:%Y-%m-%d %H:%M} server time.",
        f"- The release occurred **{alignment.minutes_into_event_candle} minutes** "
        "after the event candle opened"
        + (
            " (exactly on the candle boundary)."
            if alignment.falls_on_candle_open
            else "; the event candle therefore mixes pre- and post-release trading."
        ),
        f"- Windows: anchor k = {spec.first_relative_index}; baseline "
        f"k = {-(spec.pre_candles + spec.baseline_candles)}..{-(spec.pre_candles + 1)} "
        f"({spec.baseline_candles} candles); pre-event k = {-spec.pre_candles}..-1; "
        f"event k = 0; post-event k = 1..{spec.post_candles}.",
        "",
        "## Results",
        "",
        f"![Event-study chart]({chart_file_name})",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Reference close C(-1) | {_fmt(metrics['reference_close'], 5)} |",
        f"| Event-candle return, ln(C0/C-1) | {_signed(metrics['event_candle_return_bp'])} bp |",
        f"| Event-candle range (high-low) | {_fmt(metrics['event_candle_range_pips'], 1)} pips |",
        f"| Baseline volatility (std of hourly returns) | {_fmt(metrics['baseline_volatility_bp'])} bp |",
        f"| Event move in baseline sigmas, abs(r0)/sigma | {_fmt(metrics['event_abs_return_in_baseline_sigmas'])} |",
        f"| Event range / mean baseline range | {_fmt(metrics['event_range_vs_baseline_mean_range'])} |",
        f"| Event tick volume / baseline median | {_fmt(metrics['event_tick_volume_vs_baseline_median'])} |",
        f"| Pre-event drift (k = {-spec.pre_candles}..-1) | {_signed(metrics['pre_event_drift_bp'])} bp |",
        f"| Pre-event realised volatility | {_fmt(metrics['pre_event_realized_volatility_bp'])} bp |",
        f"| Post-event realised volatility | {_fmt(metrics['post_event_realized_volatility_bp'])} bp |",
    ]

    for horizon in report_horizons(spec):
        lines.append(
            f"| Cumulative to close of k = {horizon} | "
            f"{_signed(metrics[f'cumulative_return_bp_to_close_k{horizon}'])} bp "
            f"({_signed(metrics[f'price_change_pips_to_close_k{horizon}'], 1)} pips) |"
        )

    lines += [
        "",
        "### Candles",
        "",
        "| k | Open (UTC) | Open (server) | Open | High | Low | Close | Tick vol | Return bp | Cum. bp | Pips |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for candle in payload["candles"]:
        if candle["relative_index"] < -spec.pre_candles:
            continue

        lines.append(
            f"| {candle['relative_index']} | {candle['open_time_utc'][:16].replace('T', ' ')} "
            f"| {candle['open_time_server'][:16].replace('T', ' ')} "
            f"| {candle['open']:.5f} | {candle['high']:.5f} | {candle['low']:.5f} "
            f"| {candle['close']:.5f} | {candle['tick_volume']} "
            f"| {_signed(candle['log_return_bp'])} | {_signed(candle['cumulative_return_bp'])} "
            f"| {_signed(candle['pips_from_reference'], 1)} |"
        )

    lines += [
        "",
        f"Baseline candles (k = {-(spec.pre_candles + spec.baseline_candles)}..{-(spec.pre_candles + 1)}) "
        "are included in the JSON output.",
        "",
        "## MT5 server-offset diagnostic (tick volume)",
        "",
        "| Candidate offset | Candidate event candle (server) | Tick volume | Previous candle | Jump ratio |",
        "|---|---|---:|---:|---:|",
    ]

    for row in result.offset_diagnostic.rows:
        lines.append(
            f"| UTC{row.utc_offset_hours:+d} | {row.candidate_candle_open_server:%Y-%m-%d %H:%M} "
            f"| {_fmt(row.tick_volume)} | {_fmt(row.previous_tick_volume)} "
            f"| {_fmt(row.jump_ratio)} |"
        )

    lines += [
        "",
        f"Verdict: **{result.offset_diagnostic.verdict}**. "
        f"{result.offset_diagnostic.explanation}",
        "",
        "## Consensus surprise",
        "",
    ]

    if result.consensus.available:
        lines += [
            f"Available: {result.consensus.reason}",
            "",
            "| Component | Actual | Forecast | Surprise | Unit |",
            "|---|---:|---:|---:|---|",
        ]
        lines += [
            f"| {item.component_key} | {item.actual} | {item.forecast} "
            f"| {item.surprise:+.2f} | {item.unit} |"
            for item in result.consensus.surprises
        ]
    else:
        lines.append(f"Unavailable: {result.consensus.reason}")

    lines += [
        "",
        "## Methodology",
        "",
        "- Candle return: r_k = 10,000 x ln(C_k / C_(k-1)) basis points.",
        "- Reference price: C_(-1), the close of the last complete candle before the event candle.",
        "- Cumulative return to k: 10,000 x ln(C_k / C_(-1)); pips: (C_k - C_(-1)) x 10,000.",
        "- Baseline volatility: sample standard deviation (ddof = 1) of r_k over the baseline window.",
        "- Missing candles inside any window stop the study; nothing is filled or interpolated.",
        "- Full definitions: `docs/event_study_methodology.md`.",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in result.limitations]
    lines += [""]

    if attribution:
        lines += [
            f"{attribution}. Values are transcribed and restructured by this project.",
            "",
        ]

    lines += [
        "---",
        "",
        "Generated by `scripts/generate_eurusd_report.py`. Code: MIT licence. "
        "Third-party data remains subject to its own terms (see `DATA_SOURCES.md`). "
        "Not investment advice.",
        "",
    ]

    return "\n".join(lines)


def write_event_study_report(
    result: EventStudyResult,
    output_dir: str | Path,
    *,
    source_attribution: str | None,
) -> ReportPaths:
    """Write JSON, Markdown and PNG outputs for one study."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = output_stem(result)

    paths = ReportPaths(
        json_path=directory / f"{stem}.json",
        markdown_path=directory / f"{stem}.md",
        chart_path=directory / f"{stem}.png",
    )

    payload = build_report_payload(result, source_attribution=source_attribution)
    write_json(payload, paths.json_path)
    write_chart(result, paths.chart_path)

    markdown = build_markdown(result, payload, chart_file_name=paths.chart_path.name)

    with paths.markdown_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(markdown)

    return paths
