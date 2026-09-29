"""Tests for historical-release JSONL storage."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.economic_calendar.historical_models import (
    ComponentValueType,
    HistoricalRelease,
    HistoricalReleaseComponent,
)
from src.economic_calendar.historical_storage import (
    DuplicateHistoricalReleaseError,
    HistoricalReleaseStorage,
    HistoricalStorageError,
)

UTC = timezone.utc
US_EASTERN_WINTER = timezone(timedelta(hours=-5))
MT5_SERVER_WINTER = timezone(timedelta(hours=2))


def build_test_release(
    *,
    release_id: str = "us_test_release_2024_01_05",
    event_key: str = "us_test_event",
    release_day: int = 5,
) -> HistoricalRelease:
    """Build one valid multi-component historical release."""

    official_release_time = datetime(
        2024,
        1,
        release_day,
        8,
        30,
        tzinfo=US_EASTERN_WINTER,
    )

    utc_release_time = official_release_time.astimezone(UTC)

    mt5_server_time = utc_release_time.astimezone(MT5_SERVER_WINTER)

    return HistoricalRelease(
        release_id=release_id,
        event_key=event_key,
        reference_period="2023-12",
        official_release_time=official_release_time,
        utc_release_time=utc_release_time,
        mt5_server_time=mt5_server_time,
        official_source_name="Test Official Source",
        official_source_url="https://example.com/release",
        release_summary="Test historical economic release.",
        components=[
            HistoricalReleaseComponent(
                component_key="test_component",
                component_name="Test Component",
                value_type=ComponentValueType.NUMERIC,
                actual=100.0,
                forecast=95.0,
                previous=90.0,
                unit="index points",
            )
        ],
        notes="Storage test record.",
    )


def test_missing_storage_file_returns_empty_list(
    tmp_path: Path,
) -> None:
    """A nonexistent file should behave as empty storage."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    assert storage.load_all() == []
    assert storage.count() == 0


def test_append_and_load_one_release(
    tmp_path: Path,
) -> None:
    """One stored release should be loaded unchanged."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    release = build_test_release()

    appended_count = storage.append_many([release])
    loaded_releases = storage.load_all()

    assert appended_count == 1
    assert loaded_releases == [release]
    assert storage.count() == 1


def test_append_creates_parent_directories(
    tmp_path: Path,
) -> None:
    """Storage should create missing parent directories."""

    storage_path = tmp_path / "historical_releases" / "raw" / "releases.jsonl"

    storage = HistoricalReleaseStorage(storage_path)
    storage.append(build_test_release())

    assert storage_path.exists()


def test_duplicate_existing_release_is_rejected(
    tmp_path: Path,
) -> None:
    """An already stored release must not be stored twice."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    release = build_test_release()

    storage.append(release)

    with pytest.raises(DuplicateHistoricalReleaseError):
        storage.append(release)

    assert storage.count() == 1


def test_duplicate_inside_incoming_collection_is_rejected(
    tmp_path: Path,
) -> None:
    """Duplicates in one append operation must be rejected."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    release = build_test_release()

    with pytest.raises(DuplicateHistoricalReleaseError):
        storage.append_many([release, release])

    assert storage.count() == 0


def test_same_event_key_on_different_dates_is_allowed(
    tmp_path: Path,
) -> None:
    """Recurring publications may share an event key."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    first_release = build_test_release(
        release_id="us_test_release_2024_01_05",
        event_key="us_monthly_test_event",
        release_day=5,
    )

    second_release = build_test_release(
        release_id="us_test_release_2024_01_06",
        event_key="us_monthly_test_event",
        release_day=6,
    )

    appended_count = storage.append_many([first_release, second_release])

    assert appended_count == 2
    assert storage.count() == 2


def test_find_by_release_id(
    tmp_path: Path,
) -> None:
    """Search should return the requested release ID."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    first_release = build_test_release(
        release_id="first_release_2024_01_05",
        release_day=5,
    )

    second_release = build_test_release(
        release_id="second_release_2024_01_06",
        release_day=6,
    )

    storage.append_many([first_release, second_release])

    results = storage.find_by_release_id("first_release_2024_01_05")

    assert results == [first_release]


def test_find_by_event_key(
    tmp_path: Path,
) -> None:
    """Search should return all releases for an event rule."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    first_release = build_test_release(
        release_id="monthly_release_2024_01_05",
        event_key="monthly_event",
        release_day=5,
    )

    second_release = build_test_release(
        release_id="monthly_release_2024_01_06",
        event_key="monthly_event",
        release_day=6,
    )

    unrelated_release = build_test_release(
        release_id="other_release_2024_01_07",
        event_key="other_event",
        release_day=7,
    )

    storage.append_many(
        [
            first_release,
            second_release,
            unrelated_release,
        ]
    )

    results = storage.find_by_event_key("monthly_event")

    assert results == [
        first_release,
        second_release,
    ]


def test_contains_detects_exact_release(
    tmp_path: Path,
) -> None:
    """Contains should compare release ID and UTC time."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    release = build_test_release()

    storage.append(release)

    assert storage.contains(
        release_id=release.release_id,
        utc_release_time=release.utc_release_time,
    )

    assert not storage.contains(
        release_id=release.release_id,
        utc_release_time=(release.utc_release_time + timedelta(hours=1)),
    )


def test_invalid_jsonl_record_raises_storage_error(
    tmp_path: Path,
) -> None:
    """Invalid stored data must not be silently ignored."""

    storage_path = tmp_path / "releases.jsonl"

    storage_path.write_text(
        '{"invalid": "release"}\n',
        encoding="utf-8",
    )

    storage = HistoricalReleaseStorage(storage_path)

    with pytest.raises(HistoricalStorageError):
        storage.load_all()
