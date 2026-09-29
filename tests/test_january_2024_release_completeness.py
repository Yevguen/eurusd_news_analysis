"""Completeness audit for January 2024 historical releases.

Manifest tests always run. Tests that inspect the stored catalogue need the
PRIVATE research file data/historical_releases/raw/releases.jsonl, which is
not distributed with the public repository (see DATA_SOURCES.md); they are
skipped with an explicit reason when that file is absent.
"""

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.economic_calendar.historical_storage import (
    HistoricalReleaseStorage,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = (
    PROJECT_ROOT / "config" / "historical_release_audits" / "january_2024.yaml"
)

STORAGE_PATH = PROJECT_ROOT / "data" / "historical_releases" / "raw" / "releases.jsonl"

JANUARY_2024_START = date(2024, 1, 1)
FEBRUARY_2024_START = date(2024, 2, 1)

GERMAN_STATE_CPI_GROUP_ID = "eur_germany_state_cpi_2024_01_04"

EXPECTED_GERMAN_STATE_CPI_GEOGRAPHIES = frozenset(
    {
        "north_rhine_westphalia",
        "bavaria",
        "baden_wurttemberg",
        "hesse",
        "saxony",
        "brandenburg",
    }
)


def load_manifest() -> dict[str, Any]:
    """Load the January 2024 expected-release manifest."""

    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert isinstance(data, dict)

    return data


PRIVATE_CATALOGUE_SKIP_REASON = (
    "Private research catalogue not present "
    "(data/historical_releases/raw/releases.jsonl is intentionally not "
    "distributed with the public repository)."
)


def load_january_2024_releases() -> list[Any]:
    """Load releases officially published in January 2024."""

    if not STORAGE_PATH.is_file():
        pytest.skip(PRIVATE_CATALOGUE_SKIP_REASON)

    storage = HistoricalReleaseStorage(STORAGE_PATH)

    return [
        release
        for release in storage.load_all()
        if release.official_release_time.year == 2024
        and release.official_release_time.month == 1
    ]


def test_manifest_declares_expected_totals() -> None:
    """Manifest totals must agree with its release entries."""

    data = load_manifest()

    manifest = data["manifest"]
    releases = data["expected_releases"]

    core_count = sum(release["requirement"] == "core" for release in releases)

    conditional_count = sum(
        release["requirement"] == "activated_conditional" for release in releases
    )

    assert len(releases) == 36

    assert manifest["expected_release_count"] == len(releases)

    assert manifest["expected_core_release_count"] == core_count == 34

    assert (
        manifest["expected_activated_conditional_release_count"]
        == conditional_count
        == 2
    )


def test_manifest_release_ids_are_unique() -> None:
    """Every expected publication must have one release ID."""

    releases = load_manifest()["expected_releases"]

    release_ids = [release["release_id"] for release in releases]

    assert len(release_ids) == len(set(release_ids))


def test_manifest_publication_dates_are_in_january_2024() -> None:
    """Every expected release must be published in January."""

    releases = load_manifest()["expected_releases"]

    publication_dates = [
        date.fromisoformat(release["publication_date"]) for release in releases
    ]

    invalid_dates = [
        publication_date
        for publication_date in publication_dates
        if not (JANUARY_2024_START <= publication_date < FEBRUARY_2024_START)
    ]

    assert not invalid_dates, (
        "Manifest contains publication dates outside "
        f"January 2024: {invalid_dates!r}"
    )


def test_manifest_declares_complete_german_state_cpi_group() -> None:
    """The manifest must declare all six state CPI members."""

    groups = load_manifest()["expected_release_groups"]

    state_group = next(
        group
        for group in groups
        if group["release_group_id"] == GERMAN_STATE_CPI_GROUP_ID
    )

    actual_geographies = frozenset(state_group["expected_geography_keys"])

    assert state_group["expected_member_count"] == 6

    assert actual_geographies == EXPECTED_GERMAN_STATE_CPI_GEOGRAPHIES


def test_stored_january_release_ids_are_unique() -> None:
    """Stored January publications must not reuse release IDs."""

    releases = load_january_2024_releases()

    counts = Counter(release.release_id for release in releases)

    duplicate_ids = sorted(
        release_id for release_id, count in counts.items() if count > 1
    )

    assert not duplicate_ids, (
        "Duplicate January 2024 release IDs: " f"{duplicate_ids!r}"
    )


def test_all_expected_january_release_ids_are_present() -> None:
    """Every manifest release must exist in JSONL storage."""

    expected_releases = load_manifest()["expected_releases"]

    expected_ids = {release["release_id"] for release in expected_releases}

    actual_ids = {release.release_id for release in load_january_2024_releases()}

    missing_ids = sorted(expected_ids - actual_ids)

    assert not missing_ids, "Missing expected January 2024 releases:\n" + "\n".join(
        f"- {release_id}" for release_id in missing_ids
    )


def test_january_contains_no_unexpected_release_ids() -> None:
    """Stored January records must belong to the manifest."""

    expected_releases = load_manifest()["expected_releases"]

    expected_ids = {release["release_id"] for release in expected_releases}

    actual_ids = {release.release_id for release in load_january_2024_releases()}

    unexpected_ids = sorted(actual_ids - expected_ids)

    assert not unexpected_ids, "Unexpected January 2024 releases:\n" + "\n".join(
        f"- {release_id}" for release_id in unexpected_ids
    )
