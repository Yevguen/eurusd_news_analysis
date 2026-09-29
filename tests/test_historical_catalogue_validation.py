"""Tests for historical-release catalogue references."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.economic_calendar.historical_catalogue_validation import (
    HistoricalCatalogueReferenceError,
    HistoricalCatalogueValidator,
)
from src.economic_calendar.historical_models import (
    ComponentValueType,
    HistoricalRelease,
    HistoricalReleaseComponent,
)
from src.economic_calendar.historical_storage import (
    HistoricalReleaseStorage,
)

UTC = timezone.utc
US_EASTERN_WINTER = timezone(timedelta(hours=-5))
MT5_SERVER_WINTER = timezone(timedelta(hours=2))

GERMAN_STATE_CPI_EVENT_KEY = "eur_germany_state_cpi"

GERMAN_STATE_CPI_COMPONENT_KEYS = (
    "state_headline_cpi_mom",
    "state_headline_cpi_yoy",
)


def write_test_catalogue(
    path: Path,
    rules: dict[str, list[str]],
) -> None:
    """Write a minimal event-rule catalogue."""

    catalogue = {
        "schema_version": 1,
        "event_rules": [
            {
                "event_key": event_key,
                "components": component_keys,
            }
            for event_key, component_keys in rules.items()
        ],
    }

    path.write_text(
        yaml.safe_dump(
            catalogue,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def build_test_release(
    *,
    release_id: str = "us_test_release_2024_01_05",
    event_key: str = "us_test_event",
    component_keys: tuple[str, ...] = ("alpha_component",),
    release_group_id: str | None = None,
    geography_key: str | None = None,
    geography_name: str | None = None,
) -> HistoricalRelease:
    """Build one valid historical release."""

    official_release_time = datetime(
        2024,
        1,
        5,
        8,
        30,
        tzinfo=US_EASTERN_WINTER,
    )

    utc_release_time = official_release_time.astimezone(UTC)

    mt5_server_time = utc_release_time.astimezone(MT5_SERVER_WINTER)

    components = [
        HistoricalReleaseComponent(
            component_key=component_key,
            component_name=component_key.replace(
                "_",
                " ",
            ).title(),
            value_type=ComponentValueType.NUMERIC,
            actual=float(index * 10),
            forecast=float(index * 10 - 1),
            previous=float(index * 10 - 2),
            unit="index points",
        )
        for index, component_key in enumerate(
            component_keys,
            start=1,
        )
    ]

    return HistoricalRelease(
        release_id=release_id,
        event_key=event_key,
        release_group_id=release_group_id,
        geography_key=geography_key,
        geography_name=geography_name,
        reference_period="2023-12",
        official_release_time=official_release_time,
        utc_release_time=utc_release_time,
        mt5_server_time=mt5_server_time,
        official_source_name="Test Official Source",
        official_source_url="https://example.com/release",
        release_summary="Test release.",
        components=components,
    )


def write_german_state_cpi_catalogue(
    path: Path,
    *,
    extra_component_keys: tuple[str, ...] = (),
) -> None:
    """Write a minimal German state-CPI catalogue."""

    write_test_catalogue(
        path,
        {
            GERMAN_STATE_CPI_EVENT_KEY: [
                *GERMAN_STATE_CPI_COMPONENT_KEYS,
                *extra_component_keys,
            ],
        },
    )


def build_german_state_cpi_release(
    *,
    release_group_id: str | None = ("eur_germany_state_cpi_2024_01_04"),
    geography_key: str | None = ("north_rhine_westphalia"),
    geography_name: str | None = ("North Rhine-Westphalia"),
    component_keys: tuple[str, ...] = (GERMAN_STATE_CPI_COMPONENT_KEYS),
) -> HistoricalRelease:
    """Build one synthetic German state-CPI publication."""

    return build_test_release(
        release_id=("eur_germany_state_cpi_" "north_rhine_westphalia_2024_01_04"),
        event_key=GERMAN_STATE_CPI_EVENT_KEY,
        component_keys=component_keys,
        release_group_id=release_group_id,
        geography_key=geography_key,
        geography_name=geography_name,
    )


def test_load_catalogue_event_keys_and_components(
    tmp_path: Path,
) -> None:
    """Event keys and component keys should be indexed from YAML."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_test_event": [
                "alpha_component",
                "beta_component",
            ],
            "eur_test_event": [
                "gamma_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    assert validator.event_keys == frozenset(
        {
            "us_test_event",
            "eur_test_event",
        }
    )

    assert validator.component_keys_by_event == {
        "us_test_event": frozenset(
            {
                "alpha_component",
                "beta_component",
            }
        ),
        "eur_test_event": frozenset(
            {
                "gamma_component",
            }
        ),
    }


def test_known_event_key_and_component_keys_are_accepted(
    tmp_path: Path,
) -> None:
    """A release may reference existing event and component keys."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_test_event": [
                "alpha_component",
                "beta_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    validator.validate_release(
        build_test_release(
            event_key="us_test_event",
            component_keys=(
                "alpha_component",
                "beta_component",
            ),
        )
    )


def test_unknown_event_key_is_rejected(
    tmp_path: Path,
) -> None:
    """A release must not reference an unknown event key."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_known_event": [
                "alpha_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match=r"unknown event_key",
    ):
        validator.validate_release(
            build_test_release(
                event_key="us_unknown_event",
                component_keys=("alpha_component",),
            )
        )


def test_unknown_component_key_is_rejected(
    tmp_path: Path,
) -> None:
    """A release must not reference an unknown component key."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_test_event": [
                "alpha_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match=r"unknown component_key",
    ):
        validator.validate_release(
            build_test_release(
                event_key="us_test_event",
                component_keys=("beta_component",),
            )
        )


def test_storage_rejects_invalid_release_before_write(
    tmp_path: Path,
) -> None:
    """Invalid event keys must not enter JSONL storage."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_known_event": [
                "alpha_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    storage_path = tmp_path / "releases.jsonl"

    storage = HistoricalReleaseStorage(
        storage_path,
        catalogue_validator=validator,
    )

    with pytest.raises(HistoricalCatalogueReferenceError):
        storage.append(
            build_test_release(
                event_key="us_unknown_event",
                component_keys=("alpha_component",),
            )
        )

    assert not storage_path.exists()


def test_storage_rejects_invalid_component_before_write(
    tmp_path: Path,
) -> None:
    """Invalid component keys must not enter JSONL storage."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_test_event": [
                "alpha_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    storage_path = tmp_path / "releases.jsonl"

    storage = HistoricalReleaseStorage(
        storage_path,
        catalogue_validator=validator,
    )

    with pytest.raises(HistoricalCatalogueReferenceError):
        storage.append(
            build_test_release(
                event_key="us_test_event",
                component_keys=("beta_component",),
            )
        )

    assert not storage_path.exists()


def test_storage_detects_invalid_existing_record_with_unknown_event_key(
    tmp_path: Path,
) -> None:
    """Loading must detect an invalid event key already on disk."""

    storage_path = tmp_path / "releases.jsonl"

    unvalidated_storage = HistoricalReleaseStorage(storage_path)

    unvalidated_storage.append(
        build_test_release(
            event_key="us_unknown_event",
            component_keys=("alpha_component",),
        )
    )

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_known_event": [
                "alpha_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    validated_storage = HistoricalReleaseStorage(
        storage_path,
        catalogue_validator=validator,
    )

    with pytest.raises(HistoricalCatalogueReferenceError):
        validated_storage.load_all()


def test_storage_detects_invalid_existing_record_with_unknown_component_key(
    tmp_path: Path,
) -> None:
    """Loading must detect an invalid component key already on disk."""

    storage_path = tmp_path / "releases.jsonl"

    unvalidated_storage = HistoricalReleaseStorage(storage_path)

    unvalidated_storage.append(
        build_test_release(
            event_key="us_test_event",
            component_keys=("beta_component",),
        )
    )

    catalogue_path = tmp_path / "event_rules.yaml"

    write_test_catalogue(
        catalogue_path,
        {
            "us_test_event": [
                "alpha_component",
            ],
        },
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    validated_storage = HistoricalReleaseStorage(
        storage_path,
        catalogue_validator=validator,
    )

    with pytest.raises(HistoricalCatalogueReferenceError):
        validated_storage.load_all()


def test_complete_german_state_cpi_release_is_accepted(
    tmp_path: Path,
) -> None:
    """A complete state-CPI publication should be accepted."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_german_state_cpi_catalogue(catalogue_path)

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    validator.validate_release(build_german_state_cpi_release())


def test_german_state_cpi_requires_release_group_id(
    tmp_path: Path,
) -> None:
    """A state-CPI publication must belong to a collective group."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_german_state_cpi_catalogue(catalogue_path)

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match=("collective-group and geography metadata"),
    ) as exc_info:
        validator.validate_release(
            build_german_state_cpi_release(
                release_group_id=None,
            )
        )

    assert "release_group_id" in str(exc_info.value)


def test_german_state_cpi_requires_geography_metadata(
    tmp_path: Path,
) -> None:
    """A state-CPI publication must identify its German state."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_german_state_cpi_catalogue(catalogue_path)

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match=("collective-group and geography metadata"),
    ) as exc_info:
        validator.validate_release(
            build_german_state_cpi_release(
                geography_key=None,
                geography_name=None,
            )
        )

    error_message = str(exc_info.value)

    assert "geography_key" in error_message
    assert "geography_name" in error_message


def test_german_state_cpi_rejects_incorrect_group_prefix(
    tmp_path: Path,
) -> None:
    """The collective group must use the state-CPI prefix."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_german_state_cpi_catalogue(catalogue_path)

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match="must start with",
    ):
        validator.validate_release(
            build_german_state_cpi_release(
                release_group_id=("german_state_cpi_2024_01_04"),
            )
        )


def test_german_state_cpi_rejects_missing_component(
    tmp_path: Path,
) -> None:
    """Both MoM and YoY state-CPI components are required."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_german_state_cpi_catalogue(catalogue_path)

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match=("exactly the approved MoM and YoY"),
    ) as exc_info:
        validator.validate_release(
            build_german_state_cpi_release(
                component_keys=("state_headline_cpi_mom",),
            )
        )

    assert "state_headline_cpi_yoy" in str(exc_info.value)


def test_german_state_cpi_rejects_unexpected_component(
    tmp_path: Path,
) -> None:
    """A state-CPI release cannot contain extra CPI components."""

    catalogue_path = tmp_path / "event_rules.yaml"

    write_german_state_cpi_catalogue(
        catalogue_path,
        extra_component_keys=("state_core_cpi_yoy",),
    )

    validator = HistoricalCatalogueValidator.from_yaml(catalogue_path)

    with pytest.raises(
        HistoricalCatalogueReferenceError,
        match=("exactly the approved MoM and YoY"),
    ) as exc_info:
        validator.validate_release(
            build_german_state_cpi_release(
                component_keys=(
                    "state_headline_cpi_mom",
                    "state_headline_cpi_yoy",
                    "state_core_cpi_yoy",
                ),
            )
        )

    assert "state_core_cpi_yoy" in str(exc_info.value)
