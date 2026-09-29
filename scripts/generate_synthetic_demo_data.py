"""Regenerate the SYNTHETIC public demonstration fixtures in data/demo/.

Writes:

- data/demo/synthetic_releases.jsonl
- data/demo/SYNTHETIC_eurusd_h1_mt5_format.csv

Both files are deterministic. Run ``--check`` to verify that the committed
files match the generator without rewriting them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.demo_data.synthetic import (  # noqa: E402
    build_synthetic_candles,
    build_synthetic_releases,
    render_mt5_csv,
    render_releases_jsonl,
)

DEMO_DIR = PROJECT_ROOT / "data" / "demo"
SYNTHETIC_RELEASES_PATH = DEMO_DIR / "synthetic_releases.jsonl"
SYNTHETIC_PRICES_PATH = DEMO_DIR / "SYNTHETIC_eurusd_h1_mt5_format.csv"


def expected_outputs() -> dict[Path, str]:
    """Return the exact text each synthetic fixture file must contain."""

    return {
        SYNTHETIC_RELEASES_PATH: render_releases_jsonl(build_synthetic_releases()),
        SYNTHETIC_PRICES_PATH: render_mt5_csv(build_synthetic_candles()),
    }


def main(argv: list[str] | None = None) -> int:
    """Write or check the synthetic fixtures."""

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify that committed fixtures match the generator.",
    )
    args = parser.parse_args(argv)

    mismatches: list[Path] = []

    for path, text in expected_outputs().items():
        if args.check:
            current = (
                path.read_text(encoding="utf-8").replace("\r\n", "\n")
                if path.is_file()
                else None
            )

            if current != text:
                mismatches.append(path)

            continue

        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(text)

        print(f"Wrote SYNTHETIC fixture: {path.relative_to(PROJECT_ROOT)}")

    if mismatches:
        for path in mismatches:
            print(f"Out of date: {path.relative_to(PROJECT_ROOT)}")

        return 1

    if args.check:
        print("Synthetic fixtures are up to date.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
