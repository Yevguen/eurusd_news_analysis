"""Seed a validated historical-release JSONL catalogue from a records file.

Public demonstration (default)::

    python scripts/seed_initial_historical_releases.py

reads the SYNTHETIC records in ``data/demo/synthetic_releases.jsonl`` and
writes ``data/processed/demo/synthetic_releases.jsonl`` (git-ignored).

Private research use::

    python scripts/seed_initial_historical_releases.py \
        --input <private-records.jsonl> \
        --output data/historical_releases/raw/releases.jsonl

The January 2024 research catalogue is NOT distributed with this repository:
it mixes sources whose redistribution rights differ (see DATA_SOURCES.md).
Earlier versions of this script embedded that catalogue in code; the records
now live in private data files outside version control.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.economic_calendar.historical_catalogue_validation import (  # noqa: E402
    HistoricalCatalogueValidator,
)
from src.economic_calendar.historical_seed import (  # noqa: E402
    MixedDataOriginError,
    SeedInputError,
    load_seed_records,
    seed_storage,
)
from src.economic_calendar.historical_storage import (  # noqa: E402
    HistoricalReleaseStorage,
)

EVENT_RULES_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"

DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "demo" / "synthetic_releases.jsonl"

DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "demo" / "synthetic_releases.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    """Store seed records that are not already present."""

    parser = argparse.ArgumentParser(
        description="Seed a validated historical-release JSONL catalogue."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="JSONL file with one HistoricalRelease per line "
        "(default: the synthetic demo records).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Target JSONL catalogue (default: git-ignored demo build path).",
    )
    parser.add_argument(
        "--event-rules",
        type=Path,
        default=EVENT_RULES_PATH,
        help="Event-rule catalogue used to validate event and component keys.",
    )
    args = parser.parse_args(argv)

    try:
        records = load_seed_records(args.input)
        storage = HistoricalReleaseStorage(
            args.output,
            catalogue_validator=HistoricalCatalogueValidator.from_yaml(
                args.event_rules
            ),
        )
        result = seed_storage(records, storage)
    except (SeedInputError, MixedDataOriginError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Historical-release seeding completed.")
    print(f"Seed input: {args.input}")
    print(f"Storage file: {storage.file_path}")
    print(f"Releases appended: {result.appended_count}")
    print(f"Already present (skipped): {result.skipped_existing_count}")
    print(f"Total stored releases: {result.total_stored_count}")
    print()

    for release in storage.load_all():
        origin = release.data_origin.value if release.data_origin else "undeclared"
        print(
            f"- {release.release_id}: "
            f"event_key={release.event_key}, "
            f"origin={origin}, "
            f"components={len(release.components)}, "
            f"UTC={release.utc_release_time.isoformat()}, "
            f"MT5={release.mt5_server_time.isoformat()}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
