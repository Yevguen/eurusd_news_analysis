"""Check what a public commit of this repository would contain.

Exit status 0 means no known-prohibited content was found; 1 means findings
were reported. This is an engineering safeguard, NOT legal verification of
data rights.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_governance.publication_guard import (  # noqa: E402
    report_as_json,
    run_publication_checks,
)


def main(argv: list[str] | None = None) -> int:
    """Run all publication-safety checks and print the result."""

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON report.",
    )
    args = parser.parse_args(argv)

    report = run_publication_checks(PROJECT_ROOT)

    if args.json:
        print(report_as_json(report))
        return 0 if report.passed else 1

    print("PUBLICATION-SAFETY CHECK (engineering safeguard, not legal advice)")
    print("=" * 66)
    print(f"File listing: {report.file_listing_method}")
    print(f"Files that would be published: {report.files_considered}")
    print()

    if report.passed:
        print("PASSED: no known-prohibited content found.")
        return 0

    print(f"FAILED: {len(report.findings)} finding(s)")

    for finding in report.findings:
        print(f"- [{finding.check}] {finding.path}: {finding.message}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
