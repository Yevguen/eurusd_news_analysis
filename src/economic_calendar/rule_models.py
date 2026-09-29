"""Pydantic models and loader for the EUR/USD event-rule catalogue."""

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.economic_calendar.models import (
    Currency,
    EventType,
    ImpactLevel,
)


class StrictRuleModel(BaseModel):
    """Base model that rejects unknown catalogue fields."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ActivationType(StrEnum):
    """Controls whether an event rule is always or conditionally active."""

    CORE = "core"
    CONDITIONAL = "conditional"


class CatalogueMetadata(StrictRuleModel):
    """General information about the event-rule catalogue."""

    name: str = Field(min_length=1)
    currency_pair: Literal["EURUSD"]
    purpose: str = Field(min_length=1)


class ImpactPolicy(StrictRuleModel):
    """Human-readable definitions of the impact classifications."""

    very_high: str = Field(min_length=1)
    high: str = Field(min_length=1)
    conditional_high: str = Field(min_length=1)


class DeduplicationPolicy(StrictRuleModel):
    """Rules preventing the same publication from being counted twice."""

    one_record_per_publication: bool
    group_components_released_together: bool
    separate_records_for_different_release_times: bool


class EventRule(StrictRuleModel):
    """One validated EUR/USD event-classification rule."""

    event_key: str = Field(min_length=1)
    event_name: str = Field(min_length=1)

    currency: Currency
    country_or_region: str = Field(min_length=1)

    event_type: EventType
    impact_level: ImpactLevel
    activation: ActivationType

    event_family: str = Field(min_length=1)
    release_stage: str = Field(min_length=1)

    components: list[str] = Field(default_factory=list)

    published_condition: str | None = None
    aggregation_rule: str | None = None
    anticipation_note: str | None = None
    activation_condition: str | None = None

    @model_validator(mode="after")
    def validate_activation_rules(self) -> Self:
        """Validate requirements for conditionally active rules."""

        if (
            self.activation == ActivationType.CONDITIONAL
            and not self.activation_condition
        ):
            raise ValueError("Conditional rules must define activation_condition.")

        if (
            self.activation == ActivationType.CONDITIONAL
            and self.impact_level != ImpactLevel.HIGH
        ):
            raise ValueError("Conditional rules must use impact_level 'high'.")

        return self


class EventRuleCatalogue(StrictRuleModel):
    """Complete validated EUR/USD event-rule catalogue."""

    schema_version: Literal[1]

    catalogue: CatalogueMetadata
    impact_policy: ImpactPolicy
    deduplication_policy: DeduplicationPolicy

    event_rules: list[EventRule] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_event_keys(self) -> Self:
        """Reject duplicate event identifiers."""

        event_keys = [rule.event_key for rule in self.event_rules]

        if len(event_keys) != len(set(event_keys)):
            raise ValueError("Every event_key in the catalogue must be unique.")

        return self


def load_event_rule_catalogue(
    catalogue_path: Path,
) -> EventRuleCatalogue:
    """Load and validate the event-rule catalogue from YAML."""

    if not catalogue_path.is_file():
        raise FileNotFoundError(f"Event-rule catalogue not found: {catalogue_path}")

    with catalogue_path.open("r", encoding="utf-8") as file:
        raw_catalogue: Any = yaml.safe_load(file)

    if not isinstance(raw_catalogue, dict):
        raise ValueError("The event-rule YAML must contain a mapping.")

    return EventRuleCatalogue.model_validate(raw_catalogue)
