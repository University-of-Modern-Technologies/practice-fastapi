"""The calendar every report is cut on: Kyiv's, not UTC's.

The people reading these reports live in Kyiv, and the client draws every date
in Kyiv. A day that ended at UTC midnight would put an order placed at half
past midnight in Kyiv into the previous day's bar, and a report for "1 March"
would silently start two or three hours late. So a day here starts at Kyiv
midnight, whichever offset Kyiv happens to be on — UTC+2 in winter, UTC+3 in
summer.

The offset is read from the time-zone database rather than written down, so a
change to Ukraine's clock rules is a database update and not a code change. The
sibling backend reads the same database through ``Intl``, and resolves the one
ambiguous case the same way: a wall-clock time that a clock change skips or
repeats is read with the offset in force *before* the change — ``fold=0``, the
default of every ``datetime``. Midnight is never such a time in Kyiv, whose
clocks move at three and four in the morning, so the rule only matters for an
explicit zone-less time inside that hour.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

__all__ = [
    "DEFAULT_KYIV_WINDOW_FROM",
    "KYIV",
    "REPORT_TIME_ZONE",
    "default_kyiv_window_to",
    "kyiv_midnight",
    "kyiv_wall_clock_to_utc",
    "next_kyiv_midnight",
]

#: The zone the reports are cut in, as both the code and the SQL name it.
REPORT_TIME_ZONE: Final = "Europe/Kyiv"

KYIV: Final = ZoneInfo(REPORT_TIME_ZONE)


def kyiv_wall_clock_to_utc(value: datetime) -> datetime:
    """The UTC instant at which a Kyiv clock shows ``value``'s wall-clock time.

    ``value`` is naive; its ``fold`` is honoured, and is 0 unless somebody set
    it, which reads a skipped or repeated time with the offset before the change.
    """
    return value.replace(tzinfo=KYIV).astimezone(UTC)


def kyiv_midnight(day: date) -> datetime:
    """The instant a day of the Kyiv calendar begins, in UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=KYIV).astimezone(UTC)


def next_kyiv_midnight(now: datetime | None = None) -> datetime:
    """The next Kyiv midnight after ``now``: the exclusive end of today, in Kyiv."""
    today = (now or datetime.now(UTC)).astimezone(KYIV).date()
    return kyiv_midnight(today + timedelta(days=1))


#: Where the default report window starts: Kyiv midnight of 1 January 2026,
#: where the demonstration data begins. The shared reporting window names the
#: same calendar day; this is that day's start on the calendar reports use.
DEFAULT_KYIV_WINDOW_FROM: Final = kyiv_midnight(date(2026, 1, 1))


def default_kyiv_window_to(now: datetime | None = None) -> datetime:
    """The end of the default report window: the close of today in Kyiv."""
    return next_kyiv_midnight(now)
