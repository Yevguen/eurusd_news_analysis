"""Validated loader for the data-source registry in ``config/data_sources.yaml``.

The registry records, per publisher, which URLs and event rules belong to it
and how the project treats its data for public redistribution. The
classifications are conservative engineering decisions, not legal advice.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SOURCE_KEY_PATTERN = r"^[a-z0-9_]+$"


class RedistributionStatus(StrEnum):
    """Project classification of a source for public redistribution."""

    PERMITTED_WITH_ATTRIBUTION = "permitted_with_attribution"
    RESTRICTED = "restricted"
    UNRESOLVED = "unresolved"
    PROJECT_GENERATED = "project_generated"


PUBLISHABLE_STATUSES = frozenset(
    {
        RedistributionStatus.PERMITTED_WITH_ATTRIBUTION,
        RedistributionStatus.PROJECT_GENERATED,
    }
)


class StrictRegistryModel(BaseModel):
    """Base model that rejects unknown registry fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DataSource(StrictRegistryModel):
    """One publisher, distributor or data category."""

    source_key: str = Field(min_length=1, pattern=SOURCE_KEY_PATTERN)
    publisher: str = Field(min_length=1)
    category: str = Field(min_length=1)

    url_patterns: list[str] = Field(default_factory=list)
    event_keys: list[str] = Field(default_factory=list)

    redistribution_status: RedistributionStatus
    terms_url: str | None = None
    attribution: str | None = None
    modification_notice_required: bool
    repository_treatment: str = Field(min_length=1)

    @property
    def is_publishable(self) -> bool:
        """Whether values from this source may appear in public fixtures."""

        return self.redistribution_status in PUBLISHABLE_STATUSES

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """Require attribution and terms for sources marked reusable."""

        if self.redistribution_status == (
            RedistributionStatus.PERMITTED_WITH_ATTRIBUTION
        ):
            if not self.terms_url:
                raise ValueError(
                    f"Source {self.source_key!r} is marked reusable but "
                    "has no terms_url."
                )

            if not self.attribution:
                raise ValueError(
                    f"Source {self.source_key!r} is marked reusable but "
                    "has no attribution text."
                )

        return self

    def matches_url(self, url: str) -> bool:
        """Return whether ``url`` belongs to this source."""

        return any(_url_matches_pattern(url, pattern) for pattern in self.url_patterns)


def _url_matches_pattern(url: str, pattern: str) -> bool:
    """Match ``host[/path-prefix]`` patterns against an absolute URL.

    The host matches itself and its subdomains; the optional path prefix
    must match the start of the URL path.
    """

    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()

    pattern_host, _, pattern_path = pattern.lower().partition("/")

    host_matches = host == pattern_host or host.endswith("." + pattern_host)

    if not host_matches:
        return False

    if not pattern_path:
        return True

    return parts.path.lower().lstrip("/").startswith(pattern_path)


class SourceRegistry(StrictRegistryModel):
    """Complete validated data-source registry."""

    schema_version: Literal[1]
    policy_note: str = Field(min_length=1)
    sources: list[DataSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        """Reject duplicate keys and ambiguous URL patterns."""

        keys = [source.source_key for source in self.sources]

        if len(keys) != len(set(keys)):
            raise ValueError("Every source_key in the registry must be unique.")

        patterns = [
            pattern.lower()
            for source in self.sources
            for pattern in source.url_patterns
        ]

        if len(patterns) != len(set(patterns)):
            raise ValueError("Every url_pattern in the registry must be unique.")

        return self

    def get(self, source_key: str) -> DataSource:
        """Return one source by key."""

        for source in self.sources:
            if source.source_key == source_key:
                return source

        raise KeyError(f"Unknown source_key: {source_key!r}")

    def source_for_url(self, url: str) -> DataSource | None:
        """Return the source owning ``url``, or ``None`` when unknown.

        When several patterns match, the most specific (longest) wins.
        """

        best: tuple[int, DataSource] | None = None

        for source in self.sources:
            for pattern in source.url_patterns:
                if _url_matches_pattern(url, pattern):
                    score = len(pattern)

                    if best is None or score > best[0]:
                        best = (score, source)

        return None if best is None else best[1]

    def sources_for_event_key(self, event_key: str) -> list[DataSource]:
        """Return every source registered for an event rule."""

        return [source for source in self.sources if event_key in source.event_keys]

    def event_key_is_publishable(self, event_key: str) -> bool:
        """True only when every registered source for the key is publishable."""

        sources = self.sources_for_event_key(event_key)

        return bool(sources) and all(source.is_publishable for source in sources)


def load_source_registry(registry_path: str | Path) -> SourceRegistry:
    """Load and validate the data-source registry YAML."""

    path = Path(registry_path)

    if not path.is_file():
        raise FileNotFoundError(f"Data-source registry not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        raw_registry: Any = yaml.safe_load(file)

    if not isinstance(raw_registry, dict):
        raise ValueError("The data-source registry YAML must contain a mapping.")

    return SourceRegistry.model_validate(raw_registry)
