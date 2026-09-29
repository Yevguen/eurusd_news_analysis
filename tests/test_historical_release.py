"""Tests for historical economic-event publications."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.economic_calendar.historical_models import (
    ComponentValueType,
    HistoricalRelease,
    HistoricalReleaseComponent,
)


def valid_cpi_release_data() -> dict[str, object]:
    """Return one valid synthetic CPI publication."""

    return {
        "release_id": "us_cpi_2024_01_test",
        "event_key": "us_cpi",
        "reference_period": "Synthetic test period",
        "official_release_time": datetime.fromisoformat("2024-01-10T08:30:00-05:00"),
        "utc_release_time": datetime.fromisoformat("2024-01-10T13:30:00+00:00"),
        "mt5_server_time": datetime.fromisoformat("2024-01-10T15:30:00+02:00"),
        "official_source_name": "Synthetic official source",
        "official_source_url": ("https://example.com/official-cpi-test"),
        "forecast_source_name": "Synthetic consensus source",
        "forecast_source_url": ("https://example.com/forecast-cpi-test"),
        "components": [
            {
                "component_key": "headline_cpi",
                "component_name": "Headline CPI",
                "value_type": "numeric",
                "actual": 3.1,
                "forecast": 3.0,
                "previous": 2.9,
                "unit": "percent_year_over_year",
            },
            {
                "component_key": "core_cpi",
                "component_name": "Core CPI",
                "value_type": "numeric",
                "actual": 3.3,
                "forecast": 3.2,
                "previous": 3.1,
                "unit": "percent_year_over_year",
            },
        ],
    }


def test_create_valid_multi_component_release() -> None:
    """A valid multi-component publication should be accepted."""

    release = HistoricalRelease.model_validate(valid_cpi_release_data())

    assert release.event_key == "us_cpi"
    assert len(release.components) == 2
    assert release.components[0].actual == 3.1
    assert release.components[1].component_key == "core_cpi"


def test_reject_duplicate_component_keys() -> None:
    """A publication cannot contain duplicate component keys."""

    release_data = valid_cpi_release_data()
    components = release_data["components"]

    assert isinstance(components, list)
    second_component = components[1]

    assert isinstance(second_component, dict)
    second_component["component_key"] = "headline_cpi"

    with pytest.raises(
        ValidationError,
        match="Every component_key in a release must be unique",
    ):
        HistoricalRelease.model_validate(release_data)


def test_reject_inconsistent_mt5_time() -> None:
    """All stored timestamps must identify the same instant."""

    release_data = valid_cpi_release_data()
    release_data["mt5_server_time"] = datetime.fromisoformat(
        "2024-01-10T16:30:00+02:00"
    )

    with pytest.raises(
        ValidationError,
        match=(
            "mt5_server_time and utc_release_time " "must represent the same instant"
        ),
    ):
        HistoricalRelease.model_validate(release_data)


def test_accept_summary_only_release() -> None:
    """A qualitative publication may contain only a summary."""

    release = HistoricalRelease(
        release_id="ecb_press_conference_test",
        event_key="eur_ecb_president_press_conference",
        official_release_time=datetime.fromisoformat("2024-01-25T14:45:00+01:00"),
        utc_release_time=datetime.fromisoformat("2024-01-25T13:45:00+00:00"),
        mt5_server_time=datetime.fromisoformat("2024-01-25T15:45:00+02:00"),
        official_source_name="Synthetic ECB source",
        release_summary=("Synthetic summary used only for model testing."),
    )

    assert release.components == []
    assert release.release_summary is not None


def test_numeric_component_requires_unit() -> None:
    """A numeric observation must specify its measurement unit."""

    with pytest.raises(
        ValidationError,
        match="Numeric components must define a unit",
    ):
        HistoricalReleaseComponent(
            component_key="headline_cpi",
            component_name="Headline CPI",
            value_type=ComponentValueType.NUMERIC,
            actual=3.1,
            forecast=3.0,
            previous=2.9,
        )


def test_accept_geography_metadata_pair() -> None:
    """Geography key and readable name may be stored together."""

    release_data = valid_cpi_release_data()
    release_data["geography_key"] = "north_rhine_westphalia"
    release_data["geography_name"] = "North Rhine-Westphalia"

    release = HistoricalRelease.model_validate(release_data)

    assert release.geography_key == "north_rhine_westphalia"
    assert release.geography_name == "North Rhine-Westphalia"


def test_reject_geography_key_without_name() -> None:
    """A geography key cannot be stored without its readable name."""

    release_data = valid_cpi_release_data()
    release_data["geography_key"] = "north_rhine_westphalia"

    with pytest.raises(
        ValidationError,
        match=("geography_key and geography_name must be " "provided together"),
    ):
        HistoricalRelease.model_validate(release_data)


def test_reject_geography_name_without_key() -> None:
    """A geography name cannot be stored without its identifier key."""

    release_data = valid_cpi_release_data()
    release_data["geography_name"] = "North Rhine-Westphalia"

    with pytest.raises(
        ValidationError,
        match=("geography_key and geography_name must be " "provided together"),
    ):
        HistoricalRelease.model_validate(release_data)


def test_accept_valid_release_group_id() -> None:
    """A valid identifier may group related publications."""

    release_data = valid_cpi_release_data()
    release_data["release_group_id"] = "eur_germany_state_cpi_2024_01_04"

    release = HistoricalRelease.model_validate(release_data)

    assert release.release_group_id == ("eur_germany_state_cpi_2024_01_04")


def test_reject_invalid_release_group_id() -> None:
    """A release-group identifier must use identifier syntax."""

    release_data = valid_cpi_release_data()
    release_data["release_group_id"] = "German State CPI 2024-01-04"

    with pytest.raises(
        ValidationError,
        match="String should match pattern",
    ):
        HistoricalRelease.model_validate(release_data)
