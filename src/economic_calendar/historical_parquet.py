"""Parquet export for validated historical economic releases."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .historical_models import (
    ComponentValueType,
    HistoricalRelease,
)
from .historical_storage import HistoricalReleaseStorage

PARQUET_COLUMNS = [
    "release_id",
    "release_group_id",
    "event_key",
    "geography_key",
    "geography_name",
    "reference_period",
    "official_release_time",
    "utc_release_time",
    "mt5_server_time",
    "official_source_name",
    "official_source_url",
    "forecast_source_name",
    "forecast_source_url",
    "release_summary",
    "notes",
    "data_origin",
    "component_key",
    "component_name",
    "value_type",
    "actual_numeric",
    "forecast_numeric",
    "previous_numeric",
    "actual_text",
    "forecast_text",
    "previous_text",
    "unit",
]


def _release_level_values(
    release: HistoricalRelease,
) -> dict[str, object]:
    """Return values repeated for every component row."""

    return {
        "release_id": release.release_id,
        "release_group_id": release.release_group_id,
        "event_key": release.event_key,
        "geography_key": release.geography_key,
        "geography_name": release.geography_name,
        "reference_period": release.reference_period,
        "official_release_time": (release.official_release_time),
        "utc_release_time": release.utc_release_time,
        "mt5_server_time": release.mt5_server_time,
        "official_source_name": (release.official_source_name),
        "official_source_url": (release.official_source_url),
        "forecast_source_name": (release.forecast_source_name),
        "forecast_source_url": (release.forecast_source_url),
        "release_summary": release.release_summary,
        "notes": release.notes,
        "data_origin": (
            release.data_origin.value if release.data_origin is not None else None
        ),
    }


def flatten_release(
    release: HistoricalRelease,
) -> list[dict[str, object]]:
    """Expand one release into one analytical row per component."""

    release_values = _release_level_values(release)

    if not release.components:
        return [
            {
                **release_values,
                "component_key": None,
                "component_name": None,
                "value_type": None,
                "actual_numeric": None,
                "forecast_numeric": None,
                "previous_numeric": None,
                "actual_text": None,
                "forecast_text": None,
                "previous_text": None,
                "unit": None,
            }
        ]

    rows: list[dict[str, object]] = []

    for component in release.components:
        is_numeric = component.value_type == ComponentValueType.NUMERIC

        rows.append(
            {
                **release_values,
                "component_key": component.component_key,
                "component_name": component.component_name,
                "value_type": component.value_type.value,
                "actual_numeric": (float(component.actual) if is_numeric else None),
                "forecast_numeric": (
                    float(component.forecast)
                    if is_numeric and component.forecast is not None
                    else None
                ),
                "previous_numeric": (
                    float(component.previous)
                    if is_numeric and component.previous is not None
                    else None
                ),
                "actual_text": (str(component.actual) if not is_numeric else None),
                "forecast_text": (
                    str(component.forecast)
                    if not is_numeric and component.forecast is not None
                    else None
                ),
                "previous_text": (
                    str(component.previous)
                    if not is_numeric and component.previous is not None
                    else None
                ),
                "unit": component.unit,
            }
        )

    return rows


def build_historical_dataframe(
    storage: HistoricalReleaseStorage,
) -> pd.DataFrame:
    """Load releases and build a flattened analytical DataFrame."""

    records = [
        row for release in storage.load_all() for row in flatten_release(release)
    ]

    dataframe = pd.DataFrame(
        records,
        columns=PARQUET_COLUMNS,
    )

    if dataframe.empty:
        return dataframe

    datetime_columns = [
        "official_release_time",
        "utc_release_time",
        "mt5_server_time",
    ]

    for column in datetime_columns:
        dataframe[column] = pd.to_datetime(
            dataframe[column],
            utc=True,
        )

    dataframe = dataframe.sort_values(
        by=[
            "utc_release_time",
            "release_id",
            "component_key",
        ],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)

    return dataframe


def export_historical_parquet(
    storage: HistoricalReleaseStorage,
    parquet_path: str | Path,
) -> int:
    """Export flattened historical-release rows to Parquet."""

    target_path = Path(parquet_path)
    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataframe = build_historical_dataframe(storage)

    dataframe.to_parquet(
        target_path,
        engine="pyarrow",
        index=False,
    )

    return len(dataframe)
