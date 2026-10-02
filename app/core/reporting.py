"""The window a report covers when the caller names none.

From a fixed start to the end of today, not "the last thirty days". A window
measured backwards from the clock walks off the end of the data once enough
time has passed and reports an empty period — correct behaviour that is
indistinguishable from a broken screen. A fixed start keeps the demonstration
data in view however late the system is opened; an end at today keeps what was
entered this morning in view as well.

The start is 1 January 2026, where the demonstration data begins. The end is
the next UTC midnight, so it names a whole day: two requests on the same day
ask for the same window, and therefore hit the same cache entry, while the
next day starts a new one.

Half-open, ``[from, to)``, as every window in this codebase is: two adjacent
periods must not both claim the instant on their boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

__all__ = [
    "DEFAULT_REPORT_WINDOW_FROM",
    "DEFAULT_REPORT_WINDOW_LABEL",
    "MAX_REPORT_WINDOW_DAYS",
    "default_report_window_to",
]

DEFAULT_REPORT_WINDOW_FROM: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: Human name of the default window, for descriptions a reader sees.
DEFAULT_REPORT_WINDOW_LABEL: Final = "з 1 січня 2026 по сьогодні"

#: Widest window one report may scan. Five years: wide enough that the default
#: window, which grows by a day every day, stays valid for the life of the
#: course, and still a ceiling on what one request can walk.
MAX_REPORT_WINDOW_DAYS: Final = 1830


def default_report_window_to(now: datetime | None = None) -> datetime:
    """The next UTC midnight after ``now``: the exclusive end of today."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC) + timedelta(days=1)
