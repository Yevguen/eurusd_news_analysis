"""Data models for historical EUR/USD economic-event publications."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

IDENTIFIER_PATTERN = r"^[a-z0-9_]+$"

SYNTHETIC_RELEASE_ID_PREFIX = "synthetic_"


class StrictHistoricalModel(BaseModel):
    """Base model that rejects unknown historical-data fields."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class DataOrigin(StrEnum):
    """Provenance class of the values stored in a historical release.

    ``authentic`` records transcribe a real publication. ``synthetic``
    records are invented demonstration data and must never be read as
    historical observations. Records that predate this field (the private
    research catalogue) leave it undeclared (``None``).
    """

    AUTHENTIC = "authentic"
    SYNTHETIC = "synthetic"


class ComponentValueType(StrEnum):
    """Supported value types for release components."""

    NUMERIC = "numeric"
    TEXT = "text"


class HistoricalReleaseComponent(StrictHistoricalModel):
    """One component published inside a historical release."""

    component_key: str = Field(
        min_length=1,
        pattern=IDENTIFIER_PATTERN,
    )
    component_name: str = Field(min_length=1)

    value_type: ComponentValueType

    actual: float | str
    forecast: float | str | None = None
    previous: float | str | None = None

    unit: str | None = None

    @model_validator(mode="after")
    def validate_component_values(self) -> Self:
        """Ensure component values match their declared value type."""

        values = {
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
        }

        if self.value_type == ComponentValueType.NUMERIC:
            if not self.unit:
                raise ValueError("Numeric components must define a unit.")

            for field_name, value in values.items():
                if value is None:
                    continue

                if isinstance(value, bool) or not isinstance(
                    value,
                    (int, float),
                ):
                    raise ValueError(
                        f"{field_name} must be numeric for a " "numeric component."
                    )

        if self.value_type == ComponentValueType.TEXT:
            if self.unit is not None:
                raise ValueError("Text components must not define a unit.")

            for field_name, value in values.items():
                if value is None:
                    continue

                if not isinstance(value, str):
                    raise ValueError(
                        f"{field_name} must be text for a " "text component."
                    )

        return self


class HistoricalRelease(StrictHistoricalModel):
    """One published historical release linked to an event rule."""

    release_id: str = Field(
        min_length=1,
        pattern=IDENTIFIER_PATTERN,
    )

    event_key: str = Field(
        min_length=1,
        pattern=IDENTIFIER_PATTERN,
    )

    release_group_id: str | None = Field(
        default=None,
        pattern=IDENTIFIER_PATTERN,
    )

    geography_key: str | None = Field(
        default=None,
        pattern=IDENTIFIER_PATTERN,
    )

    geography_name: str | None = Field(
        default=None,
        min_length=1,
    )

    reference_period: str | None = Field(
        default=None,
        min_length=1,
    )

    official_release_time: datetime
    utc_release_time: datetime
    mt5_server_time: datetime

    official_source_name: str = Field(min_length=1)
    official_source_url: str | None = None

    forecast_source_name: str | None = None
    forecast_source_url: str | None = None

    release_summary: str | None = None
    components: list[HistoricalReleaseComponent] = Field(default_factory=list)

    notes: str | None = None

    data_origin: DataOrigin | None = None

    @model_validator(mode="after")
    def validate_release(self) -> Self:
        """Validate timestamps, metadata, content and component uniqueness."""

        release_times = {
            "official_release_time": self.official_release_time,
            "utc_release_time": self.utc_release_time,
            "mt5_server_time": self.mt5_server_time,
        }

        for field_name, value in release_times.items():
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a UTC offset.")

        if self.utc_release_time.utcoffset() != timedelta(0):
            raise ValueError("utc_release_time must use the UTC offset +00:00.")

        utc_instant = self.utc_release_time.astimezone(UTC)

        if self.official_release_time.astimezone(UTC) != utc_instant:
            raise ValueError(
                "official_release_time and utc_release_time "
                "must represent the same instant."
            )

        if self.mt5_server_time.astimezone(UTC) != utc_instant:
            raise ValueError(
                "mt5_server_time and utc_release_time "
                "must represent the same instant."
            )

        if (self.geography_key is None) != (self.geography_name is None):
            raise ValueError(
                "geography_key and geography_name must be " "provided together."
            )

        if not self.components and not self.release_summary:
            raise ValueError(
                "A historical release must contain components " "or a release_summary."
            )

        component_keys = [component.component_key for component in self.components]

        if len(component_keys) != len(set(component_keys)):
            raise ValueError("Every component_key in a release must be unique.")

        if self.forecast_source_url and not self.forecast_source_name:
            raise ValueError(
                "forecast_source_name is required when "
                "forecast_source_url is provided."
            )

        has_synthetic_prefix = self.release_id.startswith(SYNTHETIC_RELEASE_ID_PREFIX)
        is_synthetic = self.data_origin == DataOrigin.SYNTHETIC

        if is_synthetic and not has_synthetic_prefix:
            raise ValueError(
                "Synthetic releases must use a release_id starting with "
                f"{SYNTHETIC_RELEASE_ID_PREFIX!r}."
            )

        if has_synthetic_prefix and not is_synthetic:
            raise ValueError(
                f"A release_id starting with {SYNTHETIC_RELEASE_ID_PREFIX!r} "
                "requires data_origin 'synthetic'."
            )

        return self
