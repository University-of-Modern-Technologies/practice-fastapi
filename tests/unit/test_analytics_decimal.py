"""Report arithmetic: exact where binary floating point is not."""

from __future__ import annotations

from decimal import Decimal

from app.modules.analytics.decimal import (
    average_decimal,
    compare_decimals,
    format_decimal,
    from_scaled_integer,
    ratio,
    sum_decimals,
    to_scaled_integer,
)


class TestDecimalFormatting:
    def test_renders_money_as_a_fixed_scale_string(self) -> None:
        assert format_decimal("1234.5") == "1234.50"
        assert format_decimal("1234") == "1234.00"
        assert format_decimal(Decimal("0.1")) == "0.10"
        assert format_decimal(Decimal("19999999999.99")) == "19999999999.99"

    def test_treats_an_empty_aggregate_as_zero(self) -> None:
        # A SUM over no rows, a column the driver returned as NULL, and a value
        # that is not a decimal at all all mean "nothing", not "fail the report".
        assert format_decimal(None) == "0.00"
        assert format_decimal("not a number") == "0.00"
        assert format_decimal("1e3") == "0.00"

    def test_rounds_half_away_from_zero_without_a_float_in_sight(self) -> None:
        assert format_decimal("0.005") == "0.01"
        assert format_decimal("0.004") == "0.00"
        assert format_decimal("-0.005") == "-0.01"
        # 0.1 + 0.2 in binary floats is 0.30000000000000004; digit maths is exact.
        assert 0.1 + 0.2 != 0.3
        assert sum_decimals(["0.1", "0.2"]) == "0.30"

    def test_keeps_negative_values_signed(self) -> None:
        assert format_decimal("-12.3") == "-12.30"
        assert from_scaled_integer(-5) == "-0.05"
        assert to_scaled_integer("-12.34") == -1234

    def test_sums_many_values_exactly(self) -> None:
        assert sum_decimals([]) == "0.00"
        assert sum_decimals(["10.10", Decimal("20.20"), "0.7"]) == "31.00"

    def test_averages_with_a_guard_against_a_zero_count(self) -> None:
        assert average_decimal("100.00", 4) == "25.00"
        assert average_decimal("10.00", 3) == "3.33"
        assert average_decimal("100.00", 0) == "0.00"
        assert average_decimal(None, 5) == "0.00"

    def test_averages_a_negative_total_away_from_zero(self) -> None:
        assert average_decimal("-10.00", 3) == "-3.33"

    def test_orders_decimals_without_converting_them_to_floats(self) -> None:
        assert compare_decimals("10.00", "9.99") == 1
        assert compare_decimals("9.99", "10.00") == -1
        assert compare_decimals("10.00", "10.000") == 0

    def test_computes_a_rate_and_never_divides_by_zero(self) -> None:
        assert ratio(5, 10) == 0.5
        assert ratio(1, 3) == 0.3333
        assert ratio(0, 0) == 0
        assert ratio(7, 0) == 0

    def test_rounds_a_rate_half_up_rather_than_to_the_nearest_even(self) -> None:
        # 1/16 is exactly 0.0625, whose fourth decimal sits on the boundary.
        assert ratio(1, 16) == 0.0625
        # 3/8 = 0.375 -> 3750 tenths of a basis point, no rounding needed.
        assert ratio(3, 8) == 0.375

    def test_supports_a_scale_other_than_money(self) -> None:
        assert format_decimal("1234.5", 0) == "1235"
        assert format_decimal("1.23456", 4) == "1.2346"
