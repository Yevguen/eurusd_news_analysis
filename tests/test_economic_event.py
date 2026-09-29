"""Tests for the economic-event data model."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.economic_calendar.models import (
    Currency,
    EconomicEvent,
    EventType,
    ImpactLevel,
)


def valid_event_data() -> dict[str, object]:
    """Return valid synthetic event data for model tests."""

    return {
        "event_id": "test_us_cpi_001",
        "event_name": "US Consumer Price Index",
        "currency": Currency.USD,
        "country_or_region": "United States",
        "event_type": EventType.ECONOMIC_RELEASE,
        "impact_level": ImpactLevel.VERY_HIGH,
        "reference_period": "Synthetic test period",
        "official_release_time": datetime.fromisoformat("2024-01-10T08:30:00-05:00"),
        "utc_release_time": datetime.fromisoformat("2024-01-10T13:30:00+00:00"),
        "mt5_server_time": datetime.fromisoformat("2024-01-10T15:30:00+02:00"),
        "actual": 3.0,
        "forecast": 2.9,
        "previous": 2.8,
        "unit": "percent_year_over_year",
        "source_name": "Synthetic test source",
        "source_url": "https://example.com/test-event",
    }


def test_create_valid_economic_event() -> None:
    """A complete valid economic event should be accepted."""

    event = EconomicEvent.model_validate(valid_event_data())

    assert event.event_id == "test_us_cpi_001"
    assert event.currency == Currency.USD
    assert event.impact_level == ImpactLevel.VERY_HIGH
    assert event.actual == 3.0


def test_reject_naive_release_time() -> None:
    """A release time without a timezone must be rejected."""

    event_data = valid_event_data()
    event_data["official_release_time"] = datetime(
        2024,
        1,
        10,
        8,
        30,
    )

    with pytest.raises(
        ValidationError,
        match=r"Release timestamps must be timezone-aware\.",
    ):
        EconomicEvent.model_validate(event_data)


def test_reject_non_utc_utc_release_time() -> None:
    """utc_release_time must explicitly use the +00:00 offset."""

    event_data = valid_event_data()
    event_data["utc_release_time"] = datetime.fromisoformat("2024-01-10T14:30:00+01:00")

    with pytest.raises(
        ValidationError,
        match=r"utc_release_time must use UTC with offset \+00:00\.",
    ):
        EconomicEvent.model_validate(event_data)
