"""Persistent JSONL storage for historical economic releases."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from .historical_catalogue_validation import (
    HistoricalCatalogueValidator,
)

from .historical_models import HistoricalRelease


class HistoricalStorageError(RuntimeError):
    """Base exception for historical-release storage errors."""


class DuplicateHistoricalReleaseError(HistoricalStorageError):
    """Raised when the same historical release is stored twice."""


class HistoricalReleaseStorage:
    """Read and write validated historical releases in JSONL format.

    A release record is uniquely identified by:

    - release_id
    - utc_release_time
    """

    def __init__(
        self,
        file_path: str | Path,
        *,
        catalogue_validator: HistoricalCatalogueValidator | None = None,
    ) -> None:
        """Initialize JSONL storage and optional catalogue validation."""

        self.file_path = Path(file_path)
        self.catalogue_validator = catalogue_validator

    @staticmethod
    def _record_key(
        release: HistoricalRelease,
    ) -> tuple[str, datetime]:
        """Return the unique key of one historical release."""

        return release.release_id, release.utc_release_time

    def _validate_catalogue_references(
        self,
        releases: Iterable[HistoricalRelease],
    ) -> None:
        """Validate releases when a catalogue validator is configured."""

        if self.catalogue_validator is None:
            return

        self.catalogue_validator.validate_many(releases)

    def _ensure_parent_directory(self) -> None:
        """Create the parent directory when it does not exist."""

        self.file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def load_all(self) -> list[HistoricalRelease]:
        """Load and validate all stored historical releases."""

        if not self.file_path.exists():
            return []

        releases: list[HistoricalRelease] = []

        with self.file_path.open(
            mode="r",
            encoding="utf-8",
        ) as file:
            for line_number, raw_line in enumerate(file, start=1):
                line = raw_line.strip()

                if not line:
                    continue

                try:
                    release = HistoricalRelease.model_validate_json(line)
                except ValidationError as exc:
                    raise HistoricalStorageError(
                        "Invalid historical-release record in "
                        f"{self.file_path} at line {line_number}."
                    ) from exc

                releases.append(release)

        self._validate_catalogue_references(releases)

        return releases

    def append(self, release: HistoricalRelease) -> None:
        """Append one validated release unless it already exists."""

        self.append_many([release])

    def append_many(
        self,
        releases: Iterable[HistoricalRelease],
    ) -> int:
        """Append several validated releases and reject duplicates."""

        incoming_releases = list(releases)

        if not incoming_releases:
            return 0

        self._validate_catalogue_references(incoming_releases)
        existing_keys = {self._record_key(release) for release in self.load_all()}

        incoming_keys: set[tuple[str, datetime]] = set()

        for release in incoming_releases:
            record_key = self._record_key(release)

            if record_key in existing_keys:
                raise DuplicateHistoricalReleaseError(
                    "Historical release already exists: "
                    f"release_id={release.release_id!r}, "
                    f"utc_release_time="
                    f"{release.utc_release_time.isoformat()}."
                )

            if record_key in incoming_keys:
                raise DuplicateHistoricalReleaseError(
                    "Duplicate historical release in incoming data: "
                    f"release_id={release.release_id!r}, "
                    f"utc_release_time="
                    f"{release.utc_release_time.isoformat()}."
                )

            incoming_keys.add(record_key)

        serialized_records = "".join(
            f"{release.model_dump_json()}\n" for release in incoming_releases
        )

        self._ensure_parent_directory()

        with self.file_path.open(
            mode="a",
            encoding="utf-8",
            newline="\n",
        ) as file:
            file.write(serialized_records)

        return len(incoming_releases)

    def find_by_release_id(
        self,
        release_id: str,
    ) -> list[HistoricalRelease]:
        """Return releases with the requested release ID."""

        return [
            release for release in self.load_all() if release.release_id == release_id
        ]

    def find_by_event_key(
        self,
        event_key: str,
    ) -> list[HistoricalRelease]:
        """Return all releases linked to an event rule."""

        return [
            release for release in self.load_all() if release.event_key == event_key
        ]

    def contains(
        self,
        release_id: str,
        utc_release_time: datetime,
    ) -> bool:
        """Check whether a particular historical release exists."""

        target_key = release_id, utc_release_time

        return any(
            self._record_key(release) == target_key for release in self.load_all()
        )

    def count(self) -> int:
        """Return the total number of stored releases."""

        return len(self.load_all())
