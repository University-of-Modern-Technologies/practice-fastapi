"""The default report window: a fixed start and the end of the current day."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.core.reporting import (
    DEFAULT_REPORT_WINDOW_FROM,
    MAX_REPORT_WINDOW_DAYS,
    default_report_window_to,
)


def test_the_window_ends_at_the_next_utc_midnight() -> None:
    assert default_report_window_to(datetime(2026, 9, 30, 13, 45, tzinfo=UTC)) == datetime(
        2026, 10, 1, tzinfo=UTC
    )


def test_the_whole_day_shares_one_end_so_it_shares_one_cache_entry() -> None:
    morning = default_report_window_to(datetime(2026, 9, 30, 0, 0, tzinfo=UTC))
    night = default_report_window_to(datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC))

    assert morning == night


def test_the_day_is_read_in_utc_whatever_zone_the_clock_reports() -> None:
    kyiv = timezone(timedelta(hours=3))

    assert default_report_window_to(datetime(2026, 10, 1, 1, 0, tzinfo=kyiv)) == datetime(
        2026, 10, 1, tzinfo=UTC
    )


def test_the_default_window_fits_under_the_ceiling_for_years() -> None:
    far_ahead = default_report_window_to(datetime(2030, 12, 31, tzinfo=UTC))

    assert far_ahead - DEFAULT_REPORT_WINDOW_FROM <= timedelta(days=MAX_REPORT_WINDOW_DAYS)
