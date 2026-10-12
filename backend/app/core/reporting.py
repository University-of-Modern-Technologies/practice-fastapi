"""Bounds every report window shares.

The window a report covers when the caller names none runs from a fixed start
to the end of today, read on the Kyiv clock — see
``app.modules.analytics.kyiv_time``. A window measured backwards from the clock
walks off the end of the data once enough time has passed and reports an empty
period, which is indistinguishable from a broken screen.

Half-open, ``[from, to)``, as every window in this codebase is: two adjacent
periods must not both claim the instant on their boundary.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "DEFAULT_REPORT_WINDOW_LABEL",
    "MAX_REPORT_WINDOW_DAYS",
]

#: Human name of the default window, for descriptions a reader sees.
DEFAULT_REPORT_WINDOW_LABEL: Final = "з 1 січня 2026 по сьогодні"

#: Widest window one report may scan. Five years: wide enough that the default
#: window, which grows by a day every day, stays valid for the life of the
#: course, and still a ceiling on what one request can walk.
MAX_REPORT_WINDOW_DAYS: Final = 1830
