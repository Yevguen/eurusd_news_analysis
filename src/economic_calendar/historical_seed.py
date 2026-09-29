"""Seed a historical-release JSONL catalogue from a release-records file.

The seed input is a JSONL file with one ``HistoricalRelease`` per line (the
same layout the storage layer writes). Keeping records in data files instead
of Python code separates reusable logic from data whose redistribution rights
differ by source:

- the public repository ships SYNTHETIC records (``data/demo/``);
- the private research catalogue lives outside version control.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .historical_models import DataOrigin, HistoricalRelease
from .historical_storage import HistoricalReleaseStorage


class SeedInputError(ValueError):
    """Raised when a seed input file is missing, invalid or inconsistent."""


class MixedDataOriginError(ValueError):
    """Raised when synthetic and non-synthetic records would share a catalogue."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Outcome of one seeding run."""

    appended_count: int
    skipped_existing_count: int
    total_stored_count: int


def load_seed_records(input_path: str | Path) -> list[HistoricalRelease]:
    """Load and validate seed records, rejecting duplicate release keys."""

    path = Path(input_path)

    if not path.is_file():
        raise SeedInputError(f"Seed input file not found: {path}")

    records: list[HistoricalRelease] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                records.append(HistoricalRelease.model_validate_json(line))
            except ValidationError as exc:
                raise SeedInputError(
                    f"Invalid release record in {path} at line {line_number}."
                ) from exc

    keys: Counter[tuple[str, datetime]] = Counter(
        (record.release_id, record.utc_release_time) for record in records
    )
    duplicates = sorted(
        release_id for (release_id, _), count in keys.items() if count > 1
    )

    if duplicates:
        raise SeedInputError(f"Seed input {path} repeats release keys: {duplicates!r}.")

    return records


def _is_synthetic(release: HistoricalRelease) -> bool:
    return release.data_origin == DataOrigin.SYNTHETIC


def seed_storage(
    records: list[HistoricalRelease],
    storage: HistoricalReleaseStorage,
) -> SeedResult:
    """Append records that are not yet stored; never mix synthetic data in.

    Records already present (same ``release_id`` and ``utc_release_time``) are
    skipped, so seeding is idempotent.
    """

    existing = storage.load_all()
    catalogue_origins = {_is_synthetic(release) for release in existing}
    incoming_origins = {_is_synthetic(release) for release in records}

    if len(catalogue_origins | incoming_origins) > 1:
        raise MixedDataOriginError(
            "Refusing to mix synthetic and non-synthetic releases in one "
            f"catalogue: {storage.file_path}"
        )

    existing_keys = {
        (release.release_id, release.utc_release_time) for release in existing
    }
    missing = [
        record
        for record in records
        if (record.release_id, record.utc_release_time) not in existing_keys
    ]

    appended_count = storage.append_many(missing)

    return SeedResult(
        appended_count=appended_count,
        skipped_existing_count=len(records) - appended_count,
        total_stored_count=len(existing) + appended_count,
    )
