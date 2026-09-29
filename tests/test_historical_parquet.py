"""Tests for flattened historical-release Parquet export."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.economic_calendar.historical_models import (
    ComponentValueType,
    HistoricalRelease,
    HistoricalReleaseComponent,
)
from src.economic_calendar.historical_parquet import (
    PARQUET_COLUMNS,
    build_historical_dataframe,
    export_historical_parquet,
    flatten_release,
)
from src.economic_calendar.historical_storage import (
    HistoricalReleaseStorage,
)

UTC = timezone.utc
US_EASTERN_WINTER = timezone(timedelta(hours=-5))
MT5_SERVER_WINTER = timezone(timedelta(hours=2))


def build_multi_component_release(
    *,
    release_id: str = "us_test_release_2024_01_05",
    event_key: str = "us_test_event",
    release_day: int = 5,
    release_group_id: str | None = None,
    geography_key: str | None = None,
    geography_name: str | None = None,
) -> HistoricalRelease:

    official_release_time = datetime(
        2024,
        1,
        release_day,
        8,
        30,
        tzinfo=US_EASTERN_WINTER,
    )

    utc_release_time = official_release_time.astimezone(UTC)

    mt5_server_time = utc_release_time.astimezone(MT5_SERVER_WINTER)

    return HistoricalRelease(
        release_id=release_id,
        event_key=event_key,
        release_group_id=release_group_id,
        geography_key=geography_key,
        geography_name=geography_name,
        reference_period="2023-12",
        official_release_time=official_release_time,
        utc_release_time=utc_release_time,
        mt5_server_time=mt5_server_time,
        official_source_name="Test Official Source",
        official_source_url="https://example.com/release",
        forecast_source_name="Test Forecast Source",
        forecast_source_url="https://example.com/forecast",
        release_summary="A test multi-component release.",
        components=[
            HistoricalReleaseComponent(
                component_key="alpha_component",
                component_name="Alpha Component",
                value_type=ComponentValueType.NUMERIC,
                actual=100.0,
                forecast=95.0,
                previous=90.0,
                unit="index points",
            ),
            HistoricalReleaseComponent(
                component_key="beta_component",
                component_name="Beta Component",
                value_type=ComponentValueType.NUMERIC,
                actual=5.0,
                forecast=4.5,
                previous=4.0,
                unit="percent",
            ),
        ],
        notes="Test release notes.",
    )


def build_summary_only_release() -> HistoricalRelease:
    """Build a valid release without numeric components."""

    official_release_time = datetime(
        2024,
        1,
        31,
        14,
        0,
        tzinfo=US_EASTERN_WINTER,
    )

    utc_release_time = official_release_time.astimezone(UTC)

    mt5_server_time = utc_release_time.astimezone(MT5_SERVER_WINTER)

    return HistoricalRelease(
        release_id="us_summary_release_2024_01_31",
        event_key="us_summary_event",
        reference_period=None,
        official_release_time=official_release_time,
        utc_release_time=utc_release_time,
        mt5_server_time=mt5_server_time,
        official_source_name="Test Central Bank",
        official_source_url="https://example.com/statement",
        release_summary="Policy settings remained unchanged.",
        components=[],
        notes=None,
    )


def build_text_component_release() -> HistoricalRelease:
    """Build a release containing textual components."""

    official_release_time = datetime(
        2024,
        1,
        31,
        14,
        0,
        tzinfo=US_EASTERN_WINTER,
    )

    utc_release_time = official_release_time.astimezone(UTC)

    mt5_server_time = utc_release_time.astimezone(MT5_SERVER_WINTER)

    return HistoricalRelease(
        release_id="us_text_release_2024_01_31",
        event_key="us_test_event",
        reference_period="2024-01",
        official_release_time=official_release_time,
        utc_release_time=utc_release_time,
        mt5_server_time=mt5_server_time,
        official_source_name="Test Official Source",
        official_source_url="https://example.com/statement",
        release_summary="Test textual policy release.",
        components=[
            HistoricalReleaseComponent(
                component_key="policy_rate",
                component_name="Policy Rate",
                value_type=ComponentValueType.TEXT,
                actual="5.25%-5.50%",
                forecast=None,
                previous="5.25%-5.50%",
                unit=None,
            ),
            HistoricalReleaseComponent(
                component_key="policy_statement",
                component_name="Policy Statement",
                value_type=ComponentValueType.TEXT,
                actual="Policy remained restrictive.",
                forecast=None,
                previous="Further firming remained possible.",
                unit=None,
            ),
        ],
    )


def test_export_supports_numeric_and_text_components(
    tmp_path: Path,
) -> None:
    """Numeric and text components should coexist in Parquet."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    storage.append_many(
        [
            build_multi_component_release(),
            build_text_component_release(),
        ]
    )

    parquet_path = tmp_path / "mixed_values.parquet"

    exported_count = export_historical_parquet(
        storage=storage,
        parquet_path=parquet_path,
    )

    dataframe = pd.read_parquet(parquet_path)

    assert exported_count == 4

    numeric_rows = dataframe[dataframe["value_type"] == "numeric"]

    text_rows = dataframe[dataframe["value_type"] == "text"]

    assert numeric_rows["actual_text"].isna().all()
    assert text_rows["actual_numeric"].isna().all()

    assert set(text_rows["actual_text"]) == {
        "5.25%-5.50%",
        "Policy remained restrictive.",
    }


def test_flatten_release_creates_one_row_per_component() -> None:
    """Two components should produce two analytical rows."""

    release = build_multi_component_release()

    rows = flatten_release(release)

    assert len(rows) == 2

    assert {row["component_key"] for row in rows} == {
        "alpha_component",
        "beta_component",
    }


def test_flatten_release_preserves_release_and_component_values() -> None:
    """Flattened rows should preserve both schema levels."""

    release = build_multi_component_release()

    rows = flatten_release(release)

    alpha_row = next(row for row in rows if row["component_key"] == "alpha_component")

    assert alpha_row["release_id"] == release.release_id
    assert alpha_row["event_key"] == release.event_key
    assert alpha_row["reference_period"] == "2023-12"
    assert alpha_row["official_source_name"] == ("Test Official Source")

    assert alpha_row["component_name"] == "Alpha Component"
    assert alpha_row["value_type"] == "numeric"
    assert alpha_row["actual_numeric"] == 100.0
    assert alpha_row["forecast_numeric"] == 95.0
    assert alpha_row["previous_numeric"] == 90.0

    assert alpha_row["actual_text"] is None
    assert alpha_row["forecast_text"] is None
    assert alpha_row["previous_text"] is None

    assert alpha_row["unit"] == "index points"


def test_flatten_release_preserves_group_and_geography_metadata() -> None:
    """Every component row should retain grouping and geography metadata."""

    release = build_multi_component_release(
        release_id=("eur_germany_state_cpi_" "north_rhine_westphalia_2024_01_04"),
        event_key="eur_germany_state_cpi",
        release_group_id=("eur_germany_state_cpi_2024_01_04"),
        geography_key="north_rhine_westphalia",
        geography_name="North Rhine-Westphalia",
    )

    rows = flatten_release(release)

    assert len(rows) == 2

    assert {row["component_key"] for row in rows} == {
        "alpha_component",
        "beta_component",
    }

    for row in rows:
        assert row["release_group_id"] == ("eur_germany_state_cpi_2024_01_04")
        assert row["event_key"] == ("eur_germany_state_cpi")
        assert row["geography_key"] == ("north_rhine_westphalia")
        assert row["geography_name"] == ("North Rhine-Westphalia")


def test_summary_only_release_creates_one_row() -> None:
    """A summary-only release should remain in the dataset."""

    release = build_summary_only_release()

    rows = flatten_release(release)

    assert len(rows) == 1

    row = rows[0]

    assert row["release_id"] == release.release_id
    assert row["release_summary"] == ("Policy settings remained unchanged.")
    assert row["component_key"] is None
    assert row["component_name"] is None
    assert row["value_type"] is None

    assert row["actual_numeric"] is None
    assert row["forecast_numeric"] is None
    assert row["previous_numeric"] is None

    assert row["actual_text"] is None
    assert row["forecast_text"] is None
    assert row["previous_text"] is None

    assert row["unit"] is None


def test_build_dataframe_uses_expected_schema(
    tmp_path: Path,
) -> None:
    """The flattened table should use the declared columns."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    storage.append(build_multi_component_release())

    dataframe = build_historical_dataframe(storage)

    assert list(dataframe.columns) == PARQUET_COLUMNS
    assert len(dataframe) == 2


def test_dataframe_is_sorted_by_release_time_and_component(
    tmp_path: Path,
) -> None:
    """Rows should be ordered chronologically and by component."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    later_release = build_multi_component_release(
        release_id="later_release_2024_01_06",
        release_day=6,
    )

    earlier_release = build_multi_component_release(
        release_id="earlier_release_2024_01_05",
        release_day=5,
    )

    storage.append_many(
        [
            later_release,
            earlier_release,
        ]
    )

    dataframe = build_historical_dataframe(storage)

    assert dataframe["release_id"].tolist() == [
        "earlier_release_2024_01_05",
        "earlier_release_2024_01_05",
        "later_release_2024_01_06",
        "later_release_2024_01_06",
    ]

    assert dataframe["component_key"].tolist() == [
        "alpha_component",
        "beta_component",
        "alpha_component",
        "beta_component",
    ]


def test_dataframe_timestamp_columns_are_utc(
    tmp_path: Path,
) -> None:
    """All analytical timestamps should be normalized to UTC."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    storage.append(build_multi_component_release())

    dataframe = build_historical_dataframe(storage)

    timestamp_columns = [
        "official_release_time",
        "utc_release_time",
        "mt5_server_time",
    ]

    for column in timestamp_columns:
        assert str(dataframe[column].dtype).endswith(", UTC]")


def test_export_creates_readable_parquet_file(
    tmp_path: Path,
) -> None:
    """Parquet export should preserve flattened release rows."""

    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")

    storage.append_many(
        [
            build_multi_component_release(),
            build_summary_only_release(),
        ]
    )

    parquet_path = tmp_path / "processed" / "release_components.parquet"

    exported_count = export_historical_parquet(
        storage=storage,
        parquet_path=parquet_path,
    )

    dataframe = pd.read_parquet(parquet_path)

    assert exported_count == 3
    assert parquet_path.exists()
    assert len(dataframe) == 3
    assert list(dataframe.columns) == PARQUET_COLUMNS

    component_rows = dataframe[dataframe["component_key"].notna()]

    summary_rows = dataframe[dataframe["component_key"].isna()]

    assert len(component_rows) == 2
    assert len(summary_rows) == 1

    assert set(component_rows["actual_numeric"].dropna()) == {
        100.0,
        5.0,
    }

    summary_row = summary_rows.iloc[0]

    assert summary_row["release_id"] == ("us_summary_release_2024_01_31")
    assert pd.isna(summary_row["actual_numeric"])
    assert pd.isna(summary_row["actual_text"])
