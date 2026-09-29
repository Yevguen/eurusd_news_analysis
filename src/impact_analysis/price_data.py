"""Loading and validation of EUR/USD H1 candles exported from MetaTrader 5.

MT5 "Export bars" files are tab-separated with the header
``<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>``.
Each row is one H1 candle labelled by its OPEN time in the broker-server
clock (naive, no UTC offset). Conversion to UTC therefore needs an explicit
server-offset assumption, which this module deliberately does NOT make:
callers pass the offset they rely on (see ``event_study``).

Every price series also carries a declared provenance so that reports can
state whether numbers come from authentic or synthetic data.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pandas as pd


class PriceDataOrigin(StrEnum):
    """Declared provenance of a price series."""

    SYNTHETIC = "synthetic"
    AUTHENTIC_PRIVATE = "authentic_private"
    AUTHENTIC_REDISTRIBUTABLE = "authentic_redistributable"


PRICE_ORIGIN_LABELS: dict[PriceDataOrigin, str] = {
    PriceDataOrigin.SYNTHETIC: (
        "SYNTHETIC demonstration prices - not real market observations"
    ),
    PriceDataOrigin.AUTHENTIC_PRIVATE: (
        "AUTHENTIC market data - local/private use only, not redistributable"
    ),
    PriceDataOrigin.AUTHENTIC_REDISTRIBUTABLE: (
        "AUTHENTIC market data - redistributable under its source terms"
    ),
}


class PriceDataError(ValueError):
    """Raised when a candle file is missing, malformed or inconsistent."""


MT5_COLUMN_MAP = {
    "<DATE>": "date",
    "<TIME>": "time",
    "<OPEN>": "open",
    "<HIGH>": "high",
    "<LOW>": "low",
    "<CLOSE>": "close",
    "<TICKVOL>": "tick_volume",
    "<SPREAD>": "spread",
}

CANDLE_COLUMNS = [
    "server_open_time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
]


def load_mt5_h1_csv(csv_path: str | Path) -> pd.DataFrame:
    """Load and validate an MT5 H1 export.

    Returns a DataFrame with ``CANDLE_COLUMNS`` where ``server_open_time`` is
    a NAIVE timestamp in the broker-server clock, sorted ascending.

    Raises ``PriceDataError`` for a missing file, missing columns, unparsable
    timestamps, duplicate or unsorted candles, timestamps that are not on
    the hour, non-positive prices, or inconsistent OHLC values.
    """

    path = Path(csv_path)

    if not path.is_file():
        raise PriceDataError(f"Price file not found: {path}")

    try:
        raw = pd.read_csv(path, sep="\t", dtype=str)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise PriceDataError(f"Could not parse MT5 export {path}: {exc}") from exc

    missing = sorted(set(MT5_COLUMN_MAP) - set(raw.columns))

    if missing:
        raise PriceDataError(
            f"{path} is not an MT5 H1 export; missing columns: {missing!r}"
        )

    frame = raw[list(MT5_COLUMN_MAP)].rename(columns=MT5_COLUMN_MAP)

    if frame.empty:
        raise PriceDataError(f"{path} contains no candles.")

    timestamps = pd.to_datetime(
        frame["date"].str.strip() + " " + frame["time"].str.strip(),
        format="%Y.%m.%d %H:%M:%S",
        errors="coerce",
    )

    bad_rows = timestamps.isna()

    if bad_rows.any():
        first_bad = int(bad_rows.to_numpy().argmax()) + 2  # +1 header, +1 one-based
        raise PriceDataError(f"{path}: unparsable DATE/TIME at file line {first_bad}.")

    candles = pd.DataFrame(
        {
            "server_open_time": timestamps.astype("datetime64[ns]"),
            "open": pd.to_numeric(frame["open"], errors="coerce"),
            "high": pd.to_numeric(frame["high"], errors="coerce"),
            "low": pd.to_numeric(frame["low"], errors="coerce"),
            "close": pd.to_numeric(frame["close"], errors="coerce"),
            "tick_volume": pd.to_numeric(frame["tick_volume"], errors="coerce"),
            "spread": pd.to_numeric(frame["spread"], errors="coerce"),
        }
    )

    if candles[["open", "high", "low", "close", "tick_volume"]].isna().any().any():
        raise PriceDataError(f"{path}: non-numeric OHLC or tick-volume values.")

    _validate_candles(candles, path)

    candles["tick_volume"] = candles["tick_volume"].astype("int64")
    candles["spread"] = candles["spread"].fillna(0).astype("int64")

    return candles[CANDLE_COLUMNS].reset_index(drop=True)


def _validate_candles(candles: pd.DataFrame, path: Path) -> None:
    times = candles["server_open_time"]

    if not times.is_monotonic_increasing:
        raise PriceDataError(f"{path}: candles are not in ascending time order.")

    if times.duplicated().any():
        duplicate = times[times.duplicated()].iloc[0]
        raise PriceDataError(f"{path}: duplicate candle at {duplicate}.")

    off_hour = (times.dt.minute != 0) | (times.dt.second != 0)

    if off_hour.any():
        raise PriceDataError(
            f"{path}: H1 candles must open on the hour; found {times[off_hour].iloc[0]}."
        )

    prices = candles[["open", "high", "low", "close"]]

    if (prices <= 0).any().any():
        raise PriceDataError(f"{path}: prices must be positive.")

    body_high = candles[["open", "close"]].max(axis=1)
    body_low = candles[["open", "close"]].min(axis=1)

    inconsistent = (candles["high"] < body_high) | (candles["low"] > body_low)

    if inconsistent.any():
        first = candles.loc[inconsistent, "server_open_time"].iloc[0]
        raise PriceDataError(f"{path}: inconsistent OHLC values at {first}.")
