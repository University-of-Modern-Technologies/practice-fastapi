"""The window a report covers when the caller names none.

A fixed month, not "the last thirty days". A relative default makes the answer
to a question with no parameters depend on the day it was asked: the data in
this system sits at known dates, and a window measured backwards from the
clock walks off the end of it and reports an empty period — correct behaviour
that is indistinguishable from a broken screen.

January 2026 is where the demonstration data lives, so this is the month that
shows the system doing something. Changing it is a one-line change in one
place, which is the other reason it is a constant rather than an expression
repeated at each call site.

Half-open, ``[from, to)``, as every window in this codebase is: two adjacent
periods must not both claim the instant on their boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

__all__ = [
    "DEFAULT_REPORT_WINDOW_FROM",
    "DEFAULT_REPORT_WINDOW_LABEL",
    "DEFAULT_REPORT_WINDOW_TO",
]

DEFAULT_REPORT_WINDOW_FROM: Final = datetime(2026, 1, 1, tzinfo=UTC)

DEFAULT_REPORT_WINDOW_TO: Final = datetime(2026, 2, 1, tzinfo=UTC)

#: Human name of the window above, for descriptions a reader sees.
DEFAULT_REPORT_WINDOW_LABEL: Final = "січень 2026"
