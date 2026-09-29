"""Validate historical releases against the event-rule catalogue."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from .historical_models import HistoricalRelease

GERMAN_STATE_CPI_EVENT_KEY = "eur_germany_state_cpi"

GERMAN_STATE_CPI_COMPONENT_KEYS = frozenset(
    {
        "state_headline_cpi_mom",
        "state_headline_cpi_yoy",
    }
)

GERMAN_STATE_CPI_GROUP_PREFIX = "eur_germany_state_cpi_"


class HistoricalCatalogueReferenceError(ValueError):
    """Raised when a release has an invalid catalogue reference."""


@dataclass(frozen=True, slots=True)
class HistoricalCatalogueValidator:
    """Index and validate event keys and component keys from YAML."""

    event_keys: frozenset[str]
    component_keys_by_event: dict[str, frozenset[str]]

    @classmethod
    def from_yaml(
        cls,
        catalogue_path: str | Path,
    ) -> "HistoricalCatalogueValidator":
        """Load event keys and component keys from an event-rules YAML file."""

        path = Path(catalogue_path)

        try:
            with path.open(
                mode="r",
                encoding="utf-8",
            ) as file:
                raw_catalogue: object = yaml.safe_load(file)
        except OSError as exc:
            raise HistoricalCatalogueReferenceError(
                f"Could not read event-rule catalogue: {path}"
            ) from exc
        except yaml.YAMLError as exc:
            raise HistoricalCatalogueReferenceError(
                f"Invalid YAML in event-rule catalogue: {path}"
            ) from exc

        if not isinstance(raw_catalogue, dict):
            raise HistoricalCatalogueReferenceError(
                "The event-rule catalogue root must be a mapping."
            )

        raw_event_rules = raw_catalogue.get("event_rules")

        if not isinstance(raw_event_rules, list):
            raise HistoricalCatalogueReferenceError(
                "The event-rule catalogue must contain an " "'event_rules' list."
            )

        event_keys: set[str] = set()
        component_keys_by_event: dict[str, frozenset[str]] = {}

        for rule_number, raw_rule in enumerate(
            raw_event_rules,
            start=1,
        ):
            if not isinstance(raw_rule, dict):
                raise HistoricalCatalogueReferenceError(
                    "Every item in 'event_rules' must be a mapping. "
                    f"Invalid item number: {rule_number}."
                )

            raw_event_key = raw_rule.get("event_key")

            if not isinstance(raw_event_key, str) or not raw_event_key.strip():
                raise HistoricalCatalogueReferenceError(
                    "Every event rule must define a non-empty "
                    f"'event_key'. Invalid item number: {rule_number}."
                )

            event_key = raw_event_key.strip()

            if event_key in event_keys:
                raise HistoricalCatalogueReferenceError(
                    "Duplicate event_key in event-rule catalogue: " f"{event_key!r}."
                )

            raw_components = raw_rule.get("components", [])

            if raw_components is None:
                raw_components = []

            if not isinstance(raw_components, list):
                raise HistoricalCatalogueReferenceError(
                    f"'components' must be a list for " f"event_key={event_key!r}."
                )

            component_keys: set[str] = set()

            for component_number, raw_component_key in enumerate(
                raw_components,
                start=1,
            ):
                if (
                    not isinstance(raw_component_key, str)
                    or not raw_component_key.strip()
                ):
                    raise HistoricalCatalogueReferenceError(
                        "Every component key must be a non-empty string. "
                        f"Invalid component number {component_number} "
                        f"for event_key={event_key!r}."
                    )

                component_key = raw_component_key.strip()

                if component_key in component_keys:
                    raise HistoricalCatalogueReferenceError(
                        "Duplicate component key in event-rule catalogue: "
                        f"event_key={event_key!r}, "
                        f"component_key={component_key!r}."
                    )

                component_keys.add(component_key)

            event_keys.add(event_key)
            component_keys_by_event[event_key] = frozenset(component_keys)

        if not event_keys:
            raise HistoricalCatalogueReferenceError(
                "The event-rule catalogue contains no event keys."
            )

        return cls(
            event_keys=frozenset(event_keys),
            component_keys_by_event=component_keys_by_event,
        )

    def validate_release(
        self,
        release: HistoricalRelease,
    ) -> None:
        """Verify catalogue keys and event-specific requirements."""

        if release.event_key not in self.event_keys:
            raise HistoricalCatalogueReferenceError(
                "Historical release refers to an unknown event_key: "
                f"release_id={release.release_id!r}, "
                f"event_key={release.event_key!r}."
            )

        allowed_component_keys = self.component_keys_by_event.get(
            release.event_key,
            frozenset(),
        )

        unknown_component_keys = sorted(
            {
                component.component_key
                for component in release.components
                if component.component_key not in allowed_component_keys
            }
        )

        if unknown_component_keys:
            raise HistoricalCatalogueReferenceError(
                "Historical release contains unknown "
                "component_key values for "
                f"event_key={release.event_key!r}: "
                f"release_id={release.release_id!r}, "
                "unknown_component_keys="
                f"{unknown_component_keys!r}."
            )

        self._validate_event_specific_requirements(release)

    def _validate_event_specific_requirements(
        self,
        release: HistoricalRelease,
    ) -> None:
        """Apply requirements belonging to individual event families."""

        if release.event_key == GERMAN_STATE_CPI_EVENT_KEY:
            self._validate_german_state_cpi_release(release)

    def _validate_german_state_cpi_release(
        self,
        release: HistoricalRelease,
    ) -> None:
        """Validate one German state CPI publication."""

        release_group_id = release.release_group_id
        geography_key = release.geography_key
        geography_name = release.geography_name

        missing_metadata: list[str] = []

        if release_group_id is None:
            missing_metadata.append("release_group_id")

        if geography_key is None:
            missing_metadata.append("geography_key")

        if geography_name is None:
            missing_metadata.append("geography_name")

        if missing_metadata:
            raise HistoricalCatalogueReferenceError(
                "German state CPI releases require "
                "collective-group and geography metadata: "
                f"release_id={release.release_id!r}, "
                f"missing_fields={missing_metadata!r}."
            )

        # The missing-metadata branch above guarantees this
        # condition at runtime and informs Pylance of the type.
        assert release_group_id is not None

        if not release_group_id.startswith(GERMAN_STATE_CPI_GROUP_PREFIX):
            raise HistoricalCatalogueReferenceError(
                "German state CPI release_group_id must "
                "start with "
                f"{GERMAN_STATE_CPI_GROUP_PREFIX!r}: "
                f"release_id={release.release_id!r}, "
                f"release_group_id={release_group_id!r}."
            )

        actual_component_keys = frozenset(
            component.component_key for component in release.components
        )

        if actual_component_keys != GERMAN_STATE_CPI_COMPONENT_KEYS:
            missing_component_keys = sorted(
                GERMAN_STATE_CPI_COMPONENT_KEYS - actual_component_keys
            )

            unexpected_component_keys = sorted(
                actual_component_keys - GERMAN_STATE_CPI_COMPONENT_KEYS
            )

            raise HistoricalCatalogueReferenceError(
                "German state CPI releases must contain "
                "exactly the approved MoM and YoY "
                "headline CPI components: "
                f"release_id={release.release_id!r}, "
                "missing_component_keys="
                f"{missing_component_keys!r}, "
                "unexpected_component_keys="
                f"{unexpected_component_keys!r}."
            )

    def validate_many(
        self,
        releases: Iterable[HistoricalRelease],
    ) -> None:
        """Verify catalogue references for several releases."""

        for release in releases:
            self.validate_release(release)
