"""Display a human-readable summary of the event-rule catalogue."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.economic_calendar.models import Currency, ImpactLevel  # noqa: E402
from src.economic_calendar.rule_models import (  # noqa: E402
    ActivationType,
    load_event_rule_catalogue,
)

CATALOGUE_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"


def main() -> None:
    """Load the catalogue and print its principal statistics."""

    catalogue = load_event_rule_catalogue(CATALOGUE_PATH)

    very_high_rules = [
        rule
        for rule in catalogue.event_rules
        if rule.impact_level == ImpactLevel.VERY_HIGH
    ]

    core_high_rules = [
        rule
        for rule in catalogue.event_rules
        if (
            rule.impact_level == ImpactLevel.HIGH
            and rule.activation == ActivationType.CORE
        )
    ]

    conditional_rules = [
        rule
        for rule in catalogue.event_rules
        if rule.activation == ActivationType.CONDITIONAL
    ]

    usd_rules = [
        rule for rule in catalogue.event_rules if rule.currency == Currency.USD
    ]

    eur_rules = [
        rule for rule in catalogue.event_rules if rule.currency == Currency.EUR
    ]

    print("EUR/USD EVENT-RULE CATALOGUE")
    print("=" * 40)
    print(f"Catalogue: {catalogue.catalogue.name}")
    print(f"Currency pair: {catalogue.catalogue.currency_pair}")
    print(f"Schema version: {catalogue.schema_version}")
    print()
    print(f"Total rules: {len(catalogue.event_rules)}")
    print(f"Very-high-impact rules: {len(very_high_rules)}")
    print(f"Core high-impact rules: {len(core_high_rules)}")
    print(f"Conditional-high-impact rules: {len(conditional_rules)}")
    print()
    print(f"USD rules: {len(usd_rules)}")
    print(f"EUR rules: {len(eur_rules)}")
    print()
    print("Very-high-impact events:")

    for rule in very_high_rules:
        print(f"- [{rule.currency}] {rule.event_name}")


if __name__ == "__main__":
    main()
