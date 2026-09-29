"""Derivation of the three release timestamps stored for every publication.

Every historical release stores the same instant three times:

- ``official_release_time``: the publisher's own local clock time, with
  its UTC offset (for example 08:30 US Eastern = ``-05:00`` in winter);
- ``utc_release_time``: the same instant in UTC (``+00:00``);
- ``mt5_server_time``: the same instant expressed in the MetaTrader 5
  broker-server clock that labels the EUR/USD H1 candles.

The MT5 server offset is a PROJECT ASSUMPTION, not a verified fact. The
catalogue uses ``+02:00`` for northern-hemisphere winter releases, which is
a common broker convention (UTC+2 in winter, UTC+3 during US daylight
saving time). It has not been confirmed against the broker's own
documentation, so it is recorded as provisional wherever it is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

MT5_SERVER_WINTER_PROVISIONAL = timezone(
    timedelta(hours=2),
    name="MT5_WINTER_PROVISIONAL",
)


@dataclass(frozen=True, slots=True)
class ReleaseTimestamps:
    """The three equivalent representations of one release instant."""

    official_release_time: datetime
    utc_release_time: datetime
    mt5_server_time: datetime


def derive_release_timestamps(
    official_release_time: datetime,
    *,
    mt5_server_timezone: timezone = MT5_SERVER_WINTER_PROVISIONAL,
) -> ReleaseTimestamps:
    """Derive UTC and MT5 server timestamps from an official local time.

    Raises ``ValueError`` for a naive datetime, because an instant without
    an offset cannot be placed on the UTC timeline.
    """

    if (
        official_release_time.tzinfo is None
        or official_release_time.utcoffset() is None
    ):
        raise ValueError("official_release_time must include a UTC offset.")

    utc_release_time = official_release_time.astimezone(UTC)

    return ReleaseTimestamps(
        official_release_time=official_release_time,
        utc_release_time=utc_release_time,
        mt5_server_time=utc_release_time.astimezone(mt5_server_timezone),
    )
