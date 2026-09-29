"""Tests for provenance markers, timestamps and the public demo fixtures."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.generate_synthetic_demo_data import expected_outputs
from src.economic_calendar.historical_catalogue_validation import (
    HistoricalCatalogueValidator,
)
from src.economic_calendar.historical_models import DataOrigin, HistoricalRelease
from src.economic_calendar.historical_parquet import build_historical_dataframe
from src.economic_calendar.historical_storage import HistoricalReleaseStorage
from src.economic_calendar.timestamps import derive_release_timestamps
from src.impact_analysis.price_data import load_mt5_h1_csv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENT_RULES_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"
DEMO_DIR = PROJECT_ROOT / "data" / "demo"
SYNTHETIC_RELEASES = DEMO_DIR / "synthetic_releases.jsonl"
OFFICIAL_ALLOWLIST = DEMO_DIR / "official_releases_allowlist.jsonl"
SYNTHETIC_PRICES = DEMO_DIR / "SYNTHETIC_eurusd_h1_mt5_format.csv"


def release_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "release_id": "us_cpi_2024_01_test",
        "event_key": "us_cpi",
        "official_release_time": datetime.fromisoformat("2024-01-10T08:30:00-05:00"),
        "utc_release_time": datetime.fromisoformat("2024-01-10T13:30:00+00:00"),
        "mt5_server_time": datetime.fromisoformat("2024-01-10T15:30:00+02:00"),
        "official_source_name": "Test source",
        "release_summary": "Test summary.",
    }
    data.update(overrides)
    return data


def load_releases(path: Path) -> list[HistoricalRelease]:
    return HistoricalReleaseStorage(
        path,
        catalogue_validator=HistoricalCatalogueValidator.from_yaml(EVENT_RULES_PATH),
    ).load_all()


# ---------------------------------------------------------------------------
# data_origin marker
# ---------------------------------------------------------------------------


def test_legacy_release_without_data_origin_is_accepted() -> None:
    """Records written before the provenance field remain loadable."""

    release = HistoricalRelease.model_validate(release_data())

    assert release.data_origin is None


def test_synthetic_release_requires_synthetic_prefix() -> None:
    with pytest.raises(ValidationError, match="Synthetic releases must use"):
        HistoricalRelease.model_validate(release_data(data_origin="synthetic"))


def test_synthetic_prefix_requires_synthetic_origin() -> None:
    for origin in (None, "authentic"):
        with pytest.raises(ValidationError, match="requires data_origin 'synthetic'"):
            HistoricalRelease.model_validate(
                release_data(release_id="synthetic_us_cpi_test", data_origin=origin)
            )


def test_parquet_rows_carry_data_origin(tmp_path: Path) -> None:
    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")
    storage.append_many(load_releases(SYNTHETIC_RELEASES))

    dataframe = build_historical_dataframe(storage)

    assert set(dataframe["data_origin"]) == {"synthetic"}


# ---------------------------------------------------------------------------
# Timestamp derivation
# ---------------------------------------------------------------------------


def test_derive_release_timestamps_uses_provisional_mt5_offset() -> None:
    official = datetime(2024, 1, 11, 8, 30, tzinfo=timezone(timedelta(hours=-5)))

    stamps = derive_release_timestamps(official)

    assert stamps.utc_release_time.isoformat() == "2024-01-11T13:30:00+00:00"
    assert stamps.mt5_server_time.isoformat() == "2024-01-11T15:30:00+02:00"


def test_derive_release_timestamps_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="must include a UTC offset"):
        derive_release_timestamps(datetime(2024, 1, 11, 8, 30))


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


def test_committed_synthetic_fixtures_match_generator() -> None:
    """The committed fixtures are exactly what the generator produces."""

    for path, expected_text in expected_outputs().items():
        committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")

        assert committed == expected_text, f"{path.name} is out of date"


def test_synthetic_releases_validate_against_event_rules() -> None:
    releases = load_releases(SYNTHETIC_RELEASES)

    assert len(releases) == 5
    assert {release.event_key for release in releases} == {
        "us_cpi",
        "eur_ecb_president_press_conference",
        "eur_germany_state_cpi",
        "us_fomc_decision_statement",
    }


def test_every_synthetic_release_is_unmistakably_marked() -> None:
    for release in load_releases(SYNTHETIC_RELEASES):
        assert release.data_origin == DataOrigin.SYNTHETIC
        assert release.release_id.startswith("synthetic_")
        assert "SYNTHETIC" in release.official_source_name
        assert release.official_source_url is not None
        assert release.official_source_url.startswith("https://example.com/")
        assert release.official_release_time.year == 2030
        assert release.notes is not None and "SYNTHETIC" in release.notes


def test_synthetic_prices_are_unmistakable_and_loadable() -> None:
    candles = load_mt5_h1_csv(SYNTHETIC_PRICES)

    assert "SYNTHETIC" in SYNTHETIC_PRICES.name
    assert len(candles) == 9 * 24
    assert candles["open"].iloc[0] == pytest.approx(1.0)
    assert candles["close"].between(0.95, 1.05).all()
    assert (candles["server_open_time"].dt.dayofweek < 5).all()


def test_official_allowlist_holds_only_the_reviewed_bls_record() -> None:
    releases = load_releases(OFFICIAL_ALLOWLIST)

    assert [release.release_id for release in releases] == ["us_cpi_2024_01_11"]

    release = releases[0]

    assert release.data_origin == DataOrigin.AUTHENTIC
    assert release.official_source_url == (
        "https://www.bls.gov/news.release/archives/cpi_01112024.htm"
    )
    assert release.official_release_time.isoformat() == "2024-01-11T08:30:00-05:00"
    assert release.forecast_source_url is None

    values = {
        component.component_key: (component.actual, component.previous)
        for component in release.components
    }

    # Figures printed in the BLS release of 11 January 2024.
    assert values == {
        "headline_cpi_mom": (0.3, 0.1),
        "headline_cpi_yoy": (3.4, 3.1),
        "core_cpi_mom": (0.3, 0.3),
        "core_cpi_yoy": (3.9, 4.0),
    }

    assert all(component.forecast is None for component in release.components)
