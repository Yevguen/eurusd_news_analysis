"""Tests for the EUR/USD event-rule catalogue."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.economic_calendar.models import ImpactLevel
from src.economic_calendar.rule_models import (
    ActivationType,
    EventRule,
    load_event_rule_catalogue,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"


def test_load_complete_event_rule_catalogue() -> None:
    """The real event-rule catalogue should load successfully."""

    catalogue = load_event_rule_catalogue(CATALOGUE_PATH)

    assert catalogue.schema_version == 1
    assert catalogue.catalogue.currency_pair == "EURUSD"

    very_high_count = sum(
        rule.impact_level == ImpactLevel.VERY_HIGH for rule in catalogue.event_rules
    )

    core_high_count = sum(
        rule.impact_level == ImpactLevel.HIGH and rule.activation == ActivationType.CORE
        for rule in catalogue.event_rules
    )

    conditional_count = sum(
        rule.activation == ActivationType.CONDITIONAL for rule in catalogue.event_rules
    )

    assert len(catalogue.event_rules) == 41
    assert very_high_count == 10
    assert core_high_count == 21
    assert conditional_count == 10

    event_keys = [rule.event_key for rule in catalogue.event_rules]

    assert len(event_keys) == len(set(event_keys))


def test_conditional_rule_requires_activation_condition() -> None:
    """A conditional rule without its condition must be rejected."""

    catalogue = load_event_rule_catalogue(CATALOGUE_PATH)

    conditional_rule = next(
        rule
        for rule in catalogue.event_rules
        if rule.activation == ActivationType.CONDITIONAL
    )

    invalid_data = conditional_rule.model_dump()
    invalid_data["activation_condition"] = None

    with pytest.raises(
        ValidationError,
        match="Conditional rules must define activation_condition",
    ):
        EventRule.model_validate(invalid_data)
