"""Tests for MT5 H1 candle loading and validation."""

from pathlib import Path

import pytest

from src.impact_analysis.price_data import PriceDataError, load_mt5_h1_csv

HEADER = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"


def write_csv(path: Path, rows: list[str], header: str = HEADER) -> Path:
    path.write_text(header + "".join(row + "\n" for row in rows), encoding="utf-8")
    return path


def row(
    date: str, time: str, o: str, h: str, low: str, c: str, vol: str = "100"
) -> str:
    return "\t".join([date, time, o, h, low, c, vol, "0", "1"])


def test_load_valid_export(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "ok.csv",
        [
            row("2024.01.11", "14:00:00", "1.10000", "1.10050", "1.09950", "1.10020"),
            row(
                "2024.01.11",
                "15:00:00",
                "1.10020",
                "1.10100",
                "1.09900",
                "1.09950",
                "500",
            ),
        ],
    )

    candles = load_mt5_h1_csv(path)

    assert list(candles.columns) == [
        "server_open_time",
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
        "spread",
    ]
    assert str(candles["server_open_time"].iloc[1]) == "2024-01-11 15:00:00"
    assert candles["server_open_time"].dt.tz is None
    assert candles["tick_volume"].tolist() == [100, 500]


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(PriceDataError, match="not found"):
        load_mt5_h1_csv(tmp_path / "absent.csv")


def test_non_mt5_layout_is_rejected(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "x.csv", ["2024-01-11,1.1"], header="date,close\n")

    with pytest.raises(PriceDataError, match="missing columns"):
        load_mt5_h1_csv(path)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                row("2024.01.11", "15:00:00", "1.1", "1.2", "1.0", "1.1"),
                row("2024.01.11", "14:00:00", "1.1", "1.2", "1.0", "1.1"),
            ],
            "ascending",
        ),
        (
            [
                row("2024.01.11", "14:00:00", "1.1", "1.2", "1.0", "1.1"),
                row("2024.01.11", "14:00:00", "1.1", "1.2", "1.0", "1.1"),
            ],
            "duplicate",
        ),
        ([row("2024.01.11", "14:30:00", "1.1", "1.2", "1.0", "1.1")], "on the hour"),
        (
            [row("2024.01.11", "14:00:00", "1.1", "1.05", "1.0", "1.1")],
            "inconsistent OHLC",
        ),
        ([row("2024.01.11", "14:00:00", "0", "1.2", "0", "1.1")], "positive"),
        ([row("11/01/2024", "14:00:00", "1.1", "1.2", "1.0", "1.1")], "line 2"),
    ],
)
def test_invalid_candles_are_rejected(
    tmp_path: Path, rows: list[str], message: str
) -> None:
    path = write_csv(tmp_path / "bad.csv", rows)

    with pytest.raises(PriceDataError, match=message):
        load_mt5_h1_csv(path)
