"""Export validated historical economic releases to Parquet.

Defaults target the PRIVATE research catalogue under
data/historical_releases/ (git-ignored, not distributed). For the public
demonstration, seed the synthetic catalogue first and pass explicit paths::

    python scripts/seed_initial_historical_releases.py
    python scripts/export_historical_releases_parquet.py \
        --input data/processed/demo/synthetic_releases.jsonl \
        --output data/processed/demo/release_components.parquet
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
from src.economic_calendar.historical_parquet import (  # noqa: E402
    export_historical_parquet,
)
from src.economic_calendar.historical_storage import (  # noqa: E402
    HistoricalReleaseStorage,
)

EVENT_RULES_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"

JSONL_PATH = PROJECT_ROOT / "data" / "historical_releases" / "raw" / "releases.jsonl"

PARQUET_PATH = (
    PROJECT_ROOT
    / "data"
    / "historical_releases"
    / "processed"
    / "release_components.parquet"
)


def main(argv: list[str] | None = None) -> int:
    """Export all validated JSONL releases to Parquet."""

    parser = argparse.ArgumentParser(description="Export releases to Parquet.")
    parser.add_argument("--input", type=Path, default=JSONL_PATH)
    parser.add_argument("--output", type=Path, default=PARQUET_PATH)
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(
            f"ERROR: release catalogue not found: {args.input}\n"
            "The private research catalogue is not distributed with this "
            "repository. Use --input with a seeded catalogue (see --help).",
            file=sys.stderr,
        )
        return 2

    catalogue_validator = HistoricalCatalogueValidator.from_yaml(EVENT_RULES_PATH)

    storage = HistoricalReleaseStorage(
        args.input,
        catalogue_validator=catalogue_validator,
    )

    exported_count = export_historical_parquet(
        storage=storage,
        parquet_path=args.output,
    )

    print("Historical Parquet export completed.")
    print(f"Source JSONL: {args.input}")
    print(f"Target Parquet: {args.output}")
    print(f"Records exported: {exported_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
