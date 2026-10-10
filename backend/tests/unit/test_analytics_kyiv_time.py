"""The Kyiv calendar the reports are cut on, with the sibling backend's answers."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.analytics.kyiv_time import (
    DEFAULT_KYIV_WINDOW_FROM,
    default_kyiv_window_to,
    kyiv_midnight,
    kyiv_wall_clock_to_utc,
    next_kyiv_midnight,
)


def at(wall_clock: str) -> datetime:
    """The UTC instant a Kyiv clock shows ``wall_clock`` at, read as a client sends it."""
    return kyiv_wall_clock_to_utc(datetime.fromisoformat(wall_clock))


def test_a_winter_day_starts_at_22_utc_and_a_summer_day_at_21() -> None:
    assert kyiv_midnight(date(2026, 3, 11)) == datetime(2026, 3, 10, 22, tzinfo=UTC)
    assert kyiv_midnight(date(2026, 7, 11)) == datetime(2026, 7, 10, 21, tzinfo=UTC)


def test_the_default_window_starts_at_kyiv_midnight_of_1_january_2026() -> None:
    assert datetime(2025, 12, 31, 22, tzinfo=UTC) == DEFAULT_KYIV_WINDOW_FROM


def test_today_ends_at_the_next_kyiv_midnight_not_at_the_next_utc_one() -> None:
    """At 00:30 in Kyiv it is already "today" there, though UTC is on the day before."""
    half_past_midnight = datetime(2026, 3, 10, 22, 30, tzinfo=UTC)
    assert next_kyiv_midnight(half_past_midnight) == datetime(2026, 3, 11, 22, tzinfo=UTC)
    assert next_kyiv_midnight(datetime(2026, 3, 10, 21, 59, 59, 999_000, tzinfo=UTC)) == (
        datetime(2026, 3, 10, 22, tzinfo=UTC)
    )
    assert default_kyiv_window_to(datetime(2026, 7, 10, 21, tzinfo=UTC)) == datetime(
        2026, 7, 11, 21, tzinfo=UTC
    )


def test_the_days_of_a_clock_change_have_their_real_length() -> None:
    assert next_kyiv_midnight(datetime(2026, 3, 29, 12, tzinfo=UTC)) == datetime(
        2026, 3, 29, 21, tzinfo=UTC
    )
    assert next_kyiv_midnight(datetime(2026, 10, 25, 12, tzinfo=UTC)) == datetime(
        2026, 10, 25, 22, tzinfo=UTC
    )


def test_a_skipped_or_repeated_hour_is_read_with_the_offset_before_the_change() -> None:
    """``fold=0``, which the sibling backend reproduces on its side."""
    # 03:30 on 29 March never happens in Kyiv: the clocks jump 03:00 → 04:00.
    assert at("2026-03-29T03:30") == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    # 03:30 on 25 October happens twice; the first time is still summer time.
    assert at("2026-10-25T03:30") == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    # Clear of the change on either side, the offset of the moment applies.
    assert at("2026-03-29T05:00") == datetime(2026, 3, 29, 2, 0, tzinfo=UTC)
    assert at("2026-10-25T05:00") == datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
    assert at("2026-03-28T23:00") == datetime(2026, 3, 28, 21, 0, tzinfo=UTC)
