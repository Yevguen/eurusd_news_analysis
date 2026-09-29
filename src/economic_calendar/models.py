"""Data models for scheduled and historical EUR/USD economic events."""

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Currency(StrEnum):
    """Currencies directly relevant to EUR/USD analysis."""

    EUR = "EUR"
    USD = "USD"


class ImpactLevel(StrEnum):
    """Supported event-impact classifications."""

    HIGH = "high"
    VERY_HIGH = "very_high"


class EventType(StrEnum):
    """Main categories of economic-calendar events."""

    ECONOMIC_RELEASE = "economic_release"
    CENTRAL_BANK_DECISION = "central_bank_decision"
    CENTRAL_BANK_SPEECH = "central_bank_speech"
    OFFICIAL_STATEMENT = "official_statement"


class EconomicEvent(BaseModel):
    """One scheduled or historical high-impact EUR/USD event."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    event_id: str = Field(min_length=1)
    event_name: str = Field(min_length=1)

    currency: Currency
    country_or_region: str = Field(min_length=1)

    event_type: EventType
    impact_level: ImpactLevel

    reference_period: str | None = None

    official_release_time: datetime
    utc_release_time: datetime
    mt5_server_time: datetime

    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None

    unit: str | None = None

    source_name: str = Field(min_length=1)
    source_url: str | None = None

    @field_validator(
        "official_release_time",
        "utc_release_time",
        "mt5_server_time",
    )
    @classmethod
    def require_timezone_aware_datetime(cls, value: datetime) -> datetime:
        """Reject datetimes that have no UTC offset."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Release timestamps must be timezone-aware.")

        return value

    @field_validator("utc_release_time")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        """Require utc_release_time to have a zero UTC offset."""

        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("utc_release_time must use UTC with offset +00:00.")

        return value

    @model_validator(mode="after")
    def verify_release_times_represent_same_instant(
        self,
    ) -> "EconomicEvent":
        """Ensure all three timestamps describe the same release instant."""

        official_as_utc = self.official_release_time.astimezone(timezone.utc)
        mt5_as_utc = self.mt5_server_time.astimezone(timezone.utc)

        if official_as_utc != self.utc_release_time:
            raise ValueError(
                "official_release_time and utc_release_time "
                "do not represent the same instant."
            )

        if mt5_as_utc != self.utc_release_time:
            raise ValueError(
                "mt5_server_time and utc_release_time "
                "do not represent the same instant."
            )

        return self
