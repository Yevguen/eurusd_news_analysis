"""Validated loading of project settings from YAML."""

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictSettingsModel(BaseModel):
    """Base model that rejects unknown configuration fields."""

    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictSettingsModel):
    """General project settings."""

    name: str = Field(min_length=1)
    currency_pair: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)


class AnalysisPeriodConfig(StrictSettingsModel):
    """Starting dates for event and price-data analysis."""

    event_start_date: date
    market_data_start_date: date


class TimeSettingsConfig(StrictSettingsModel):
    """Timestamp-storage rules."""

    primary_timestamp_system: str = Field(min_length=1)
    store_official_release_time: bool
    store_utc_release_time: bool
    require_timezone_aware_datetimes: bool


class DataPolicyConfig(StrictSettingsModel):
    """Rules controlling which events are included."""

    include_scheduled_releases: bool
    include_central_bank_decisions: bool
    include_central_bank_speeches: bool
    include_official_statements: bool
    include_medium_impact_events: bool
    include_low_impact_events: bool


class ProjectSettings(StrictSettingsModel):
    """Complete validated project configuration."""

    project: ProjectConfig
    analysis_period: AnalysisPeriodConfig
    supported_currencies: list[str]
    supported_impact_levels: list[str]
    time_settings: TimeSettingsConfig
    data_policy: DataPolicyConfig


def load_project_settings(settings_path: Path) -> ProjectSettings:
    """Load and validate project settings from a YAML file."""

    if not settings_path.is_file():
        raise FileNotFoundError(f"Project settings file not found: {settings_path}")

    with settings_path.open("r", encoding="utf-8") as file:
        raw_settings: Any = yaml.safe_load(file)

    if not isinstance(raw_settings, dict):
        raise ValueError("The project settings YAML must contain a mapping.")

    return ProjectSettings.model_validate(raw_settings)
