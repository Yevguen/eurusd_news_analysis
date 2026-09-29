"""Tests for project-settings loading and validation."""

from datetime import date
from pathlib import Path

from src.settings import load_project_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "config" / "project_settings.yaml"


def test_load_project_settings() -> None:
    """The real project settings file should load successfully."""

    settings = load_project_settings(SETTINGS_PATH)

    assert settings.project.name == "eurusd_news_analysis"
    assert settings.project.currency_pair == "EURUSD"
    assert settings.project.timeframe == "H1"

    assert settings.analysis_period.event_start_date == date(
        2024,
        1,
        1,
    )
    assert settings.analysis_period.market_data_start_date == date(
        2023,
        12,
        1,
    )

    assert settings.supported_currencies == ["EUR", "USD"]
    assert settings.supported_impact_levels == [
        "high",
        "very_high",
    ]

    assert settings.time_settings.primary_timestamp_system == "mt5_server_time"
    assert settings.data_policy.include_medium_impact_events is False
    assert settings.data_policy.include_low_impact_events is False
