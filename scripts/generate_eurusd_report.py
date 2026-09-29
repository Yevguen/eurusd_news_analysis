"""Generate a single-event EUR/USD H1 event-study report.

Public demonstration (authentic BLS release + SYNTHETIC prices)::

    python scripts/generate_eurusd_report.py --demo

Local analysis with your own MT5 export (results stay git-ignored)::

    python scripts/generate_eurusd_report.py \
        --releases data/demo/official_releases_allowlist.jsonl \
        --release-id us_cpi_2024_01_11 \
        --prices <path-to-your-EURUSD_H1-MT5-export.csv> \
        --price-data-origin authentic_private

Outputs (JSON, Markdown, PNG) are written to ``data/reports/<origin>/`` by
default. Reports built from ``authentic_private`` prices may only be written
under ``data/reports/`` or outside the repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_governance.publication_guard import (  # noqa: E402
    DEMO_MANIFEST_RELATIVE_PATH,
    load_demo_manifest,
)
from src.data_governance.source_registry import load_source_registry  # noqa: E402
from src.economic_calendar.historical_catalogue_validation import (  # noqa: E402
    HistoricalCatalogueReferenceError,
    HistoricalCatalogueValidator,
)
from src.economic_calendar.historical_models import HistoricalRelease  # noqa: E402
from src.economic_calendar.historical_storage import (  # noqa: E402
    HistoricalReleaseStorage,
    HistoricalStorageError,
)
from src.impact_analysis.consensus import evaluate_consensus  # noqa: E402
from src.impact_analysis.event_study import (  # noqa: E402
    EventStudyError,
    EventWindowSpec,
    run_event_study,
)
from src.impact_analysis.price_data import (  # noqa: E402
    PriceDataError,
    PriceDataOrigin,
    load_mt5_h1_csv,
)
from src.reporting.event_study_report import write_event_study_report  # noqa: E402

EVENT_RULES_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_sources.yaml"
REPORTS_ROOT = PROJECT_ROOT / "data" / "reports"

DEMO_RELEASES_PATH = (
    PROJECT_ROOT / "data" / "demo" / "official_releases_allowlist.jsonl"
)
DEMO_RELEASE_ID = "us_cpi_2024_01_11"
DEMO_PRICES_PATH = PROJECT_ROOT / "data" / "demo" / "SYNTHETIC_eurusd_h1_mt5_format.csv"


class ReportInputError(ValueError):
    """Raised for missing or inconsistent command-line inputs."""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False

    return True


def select_release(releases_path: Path, release_id: str) -> HistoricalRelease:
    """Load a validated catalogue file and return exactly one release."""

    if not releases_path.is_file():
        raise ReportInputError(f"Release catalogue not found: {releases_path}")

    storage = HistoricalReleaseStorage(
        releases_path,
        catalogue_validator=HistoricalCatalogueValidator.from_yaml(EVENT_RULES_PATH),
    )
    matches = storage.find_by_release_id(release_id)

    if not matches:
        available = ", ".join(sorted(r.release_id for r in storage.load_all())[:10])
        raise ReportInputError(
            f"release_id {release_id!r} not found in {releases_path}. "
            f"Available (first 10): {available or 'none'}"
        )

    if len(matches) > 1:
        raise ReportInputError(
            f"release_id {release_id!r} is ambiguous in {releases_path} "
            f"({len(matches)} records)."
        )

    return matches[0]


def check_declared_price_origin(prices_path: Path, origin: PriceDataOrigin) -> None:
    """Refuse to relabel a manifest-declared demo price file."""

    manifest_path = PROJECT_ROOT / DEMO_MANIFEST_RELATIVE_PATH

    if not manifest_path.is_file():
        return

    for entry in load_demo_manifest(manifest_path).files:
        declared = PROJECT_ROOT / entry.path

        if (
            declared.resolve() == prices_path.resolve()
            and entry.data_origin != origin.value
        ):
            raise ReportInputError(
                f"{entry.path} is declared as {entry.data_origin!r} in the demo "
                f"manifest; it cannot be analysed as {origin.value!r}."
            )


def check_output_location(output_dir: Path, origin: PriceDataOrigin) -> None:
    """Keep reports derived from private prices out of publishable folders."""

    if origin != PriceDataOrigin.AUTHENTIC_PRIVATE:
        return

    if _is_within(output_dir, REPORTS_ROOT) or not _is_within(output_dir, PROJECT_ROOT):
        return

    raise ReportInputError(
        "Reports built from authentic_private prices must be written under "
        "data/reports/ (git-ignored) or outside the repository; refusing "
        f"{output_dir}."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a single-event EUR/USD H1 event-study report."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the public demo: BLS CPI release (2024-01-11) with SYNTHETIC prices.",
    )
    parser.add_argument("--releases", type=Path, help="Release catalogue (JSONL).")
    parser.add_argument("--release-id", help="release_id of the event to study.")
    parser.add_argument("--prices", type=Path, help="MT5 H1 export (tab-separated).")
    parser.add_argument(
        "--price-data-origin",
        choices=[origin.value for origin in PriceDataOrigin],
        help="Provenance of the price file (required with --prices).",
    )
    parser.add_argument(
        "--price-source-description",
        help="Free-text description of the price source for the report.",
    )
    parser.add_argument("--output-dir", type=Path, help="Output directory.")
    parser.add_argument("--pre-candles", type=int, default=6)
    parser.add_argument("--post-candles", type=int, default=6)
    parser.add_argument("--baseline-candles", type=int, default=24)

    return parser


def resolve_inputs(
    args: argparse.Namespace,
) -> tuple[Path, str, Path, PriceDataOrigin, str, Path]:
    """Apply --demo defaults and validate the combination of arguments."""

    if args.demo:
        releases = args.releases or DEMO_RELEASES_PATH
        release_id = args.release_id or DEMO_RELEASE_ID
        prices = args.prices or DEMO_PRICES_PATH
        origin = PriceDataOrigin(args.price_data_origin or PriceDataOrigin.SYNTHETIC)
    else:
        missing = [
            flag
            for flag, value in (
                ("--releases", args.releases),
                ("--release-id", args.release_id),
                ("--prices", args.prices),
                ("--price-data-origin", args.price_data_origin),
            )
            if value is None
        ]

        if missing:
            raise ReportInputError(
                "Missing required argument(s): "
                + ", ".join(missing)
                + ". Use --demo for the public demonstration."
            )

        releases = args.releases
        release_id = args.release_id
        prices = args.prices
        origin = PriceDataOrigin(args.price_data_origin)

    if not prices.is_file():
        raise ReportInputError(f"Price file not found: {prices}")

    description = args.price_source_description or (
        f"{prices.name} (MT5 H1 export layout)"
    )
    output_dir = args.output_dir or (
        REPORTS_ROOT / ("demo" if args.demo else origin.value)
    )

    check_declared_price_origin(prices, origin)
    check_output_location(output_dir, origin)

    return releases, release_id, prices, origin, description, output_dir


def main(argv: list[str] | None = None) -> int:
    """Generate the report; return 0 on success and 2 on input errors."""

    args = build_parser().parse_args(argv)

    try:
        releases, release_id, prices, origin, description, output_dir = resolve_inputs(
            args
        )
        spec = EventWindowSpec(
            pre_candles=args.pre_candles,
            post_candles=args.post_candles,
            baseline_candles=args.baseline_candles,
        )
        release = select_release(releases, release_id)
        registry = load_source_registry(REGISTRY_PATH)
        candles = load_mt5_h1_csv(prices)
        result = run_event_study(
            release,
            candles,
            price_data_origin=origin,
            price_source_description=description,
            consensus=evaluate_consensus(release, registry),
            spec=spec,
        )
    except (
        ReportInputError,
        EventStudyError,
        PriceDataError,
        HistoricalStorageError,
        HistoricalCatalogueReferenceError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    source = (
        registry.source_for_url(release.official_source_url)
        if release.official_source_url
        else None
    )
    attribution = (
        source.attribution if source is not None and source.is_publishable else None
    )

    paths = write_event_study_report(result, output_dir, source_attribution=attribution)
    metrics = result.metrics

    print("EUR/USD event-study report generated.")
    print(f"Event: {release.release_id} at {release.utc_release_time.isoformat()}")
    print(f"Market data: {result.price_origin_label}")
    print(f"Event-candle return: {metrics['event_candle_return_bp']:+.2f} bp")
    print(f"Consensus surprise available: {result.consensus.available}")
    print(f"JSON: {paths.json_path}")
    print(f"Markdown: {paths.markdown_path}")
    print(f"Chart: {paths.chart_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
