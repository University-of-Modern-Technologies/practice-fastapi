"""Wire formats that two independent backends must agree on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.serializers import format_datetime, format_money, format_scaled_money


def test_instant_is_rendered_with_exactly_three_fractional_digits() -> None:
    moment = datetime(2026, 8, 12, 15, 23, 45, 123_456, tzinfo=UTC)

    assert format_datetime(moment) == "2026-08-12T15:23:45.123Z"


def test_whole_second_still_carries_the_fraction() -> None:
    moment = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    assert format_datetime(moment) == "2026-01-01T00:00:00.000Z"


def test_other_zones_are_converted_rather_than_relabelled() -> None:
    moment = datetime(2026, 8, 12, 17, 23, 45, tzinfo=timezone(timedelta(hours=2)))

    assert format_datetime(moment) == "2026-08-12T15:23:45.000Z"


def test_naive_value_is_read_as_utc() -> None:
    moment = datetime(2026, 8, 12, 15, 23, 45)  # noqa: DTZ001 - the case under test

    assert format_datetime(moment) == "2026-08-12T15:23:45.000Z"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        # A trailing zero is not information: the sibling backend renders a
        # stored amount through a decimal library that drops it, and a client
        # comparing the two responses byte for byte would otherwise see a
        # difference on every monetary field.
        (Decimal("12.50"), "12.5"),
        (Decimal("12.5"), "12.5"),
        (Decimal("2400.00"), "2400"),
        (Decimal("12"), "12"),
        (Decimal("0.00"), "0"),
        (Decimal("0"), "0"),
        (Decimal("1234.56"), "1234.56"),
        # Nothing is rounded on the way out: the scale a value carries is the
        # scale it was computed at, and the wire format only reports it.
        (Decimal("1234.567"), "1234.567"),
        (Decimal("-3.40"), "-3.4"),
        (Decimal("-0.05"), "-0.05"),
    ],
)
def test_amounts_are_rendered_in_shortest_exact_form(amount: Decimal, expected: str) -> None:
    assert format_money(amount) == expected


@pytest.mark.parametrize(
    "amount",
    [
        # `normalize` is what strips the trailing zeros, and it is also what
        # turns a round number into an exponent form. Every one of these is a
        # value whose normalised form carries a positive exponent.
        Decimal("2400.00"),
        Decimal("1E+3"),
        Decimal("100000000000.00"),
        Decimal("999999999999.00"),
        Decimal("-1E+6"),
    ],
)
def test_a_large_amount_never_reaches_the_wire_as_an_exponent(amount: Decimal) -> None:
    rendered = format_money(amount)

    assert "E" not in rendered.upper()
    assert Decimal(rendered) == amount


def test_an_amount_read_from_the_database_loses_its_padding() -> None:
    # `Numeric(14, 2)` always hands back two decimals, so the column is exactly
    # the case the format has to normalise.
    from_column = Decimal("37.50")

    assert format_money(from_column) == "37.5"
    assert format_money(Decimal("0.00")) == "0"
    assert format_money(Decimal("9999999990.00")) == "9999999990"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("12.5"), "12.50"),
        (Decimal("12"), "12.00"),
        (Decimal("0"), "0.00"),
        (Decimal("1234.567"), "1234.57"),
        (Decimal("-3.4"), "-3.40"),
    ],
)
def test_a_report_figure_keeps_its_fixed_scale(amount: Decimal, expected: str) -> None:
    assert format_scaled_money(amount) == expected
