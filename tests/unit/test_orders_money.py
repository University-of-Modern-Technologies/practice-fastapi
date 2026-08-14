"""Order arithmetic: exact where binary floating point is not."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.core.serializers import format_money, format_scaled_money
from app.modules.orders.money import (
    ZERO_MONEY,
    calculate_line_total,
    calculate_order_totals,
    normalize_money,
)


class TestMoneyNormalisation:
    def test_pins_the_scale_of_every_accepted_representation(self) -> None:
        assert normalize_money("19.99") == Decimal("19.99")
        assert normalize_money("19.9") == Decimal("19.90")
        assert normalize_money("19") == Decimal("19.00")
        # The driver renders Numeric(14, 2) without trailing zeros, which must
        # not turn into a different amount internally.
        assert format_scaled_money(normalize_money(Decimal("19.9"))) == "19.90"
        assert format_scaled_money(normalize_money(Decimal("0"))) == "0.00"
        # On the wire the padding comes back off again, matching the sibling
        # backend rather than the scale the arithmetic happens to use.
        assert format_money(normalize_money(Decimal("19.9"))) == "19.9"
        assert format_money(normalize_money(Decimal("0"))) == "0"

    @pytest.mark.parametrize("value", ["-1.00", "1.005", "abc", "", "1e3", " ", "1_000"])
    def test_rejects_anything_that_is_not_a_non_negative_amount(self, value: str) -> None:
        with pytest.raises(AppError) as error:
            normalize_money(value)
        assert error.value.code == "INVALID_MONETARY_AMOUNT"
        assert error.value.status_code == 400

    @pytest.mark.parametrize(
        "value", [Decimal("-0.01"), Decimal("1.005"), Decimal("NaN"), Decimal("1E+13")]
    )
    def test_rejects_the_same_amounts_when_they_arrive_as_decimals(self, value: Decimal) -> None:
        with pytest.raises(AppError) as error:
            normalize_money(value)
        assert error.value.code == "INVALID_MONETARY_AMOUNT"


class TestLineTotal:
    def test_multiplies_the_snapshot_price_by_the_quantity(self) -> None:
        assert calculate_line_total("19.99", 7) == Decimal("139.93")
        assert calculate_line_total(Decimal("0.07"), 3) == Decimal("0.21")

    def test_stays_exact_where_the_float_path_is_demonstrably_wrong(self) -> None:
        assert 0.07 * 3 != 0.21
        assert 19.99 * 7 != 139.93

        assert format_scaled_money(calculate_line_total("0.07", 3)) == "0.21"
        assert format_scaled_money(calculate_line_total("19.99", 7)) == "139.93"

    @pytest.mark.parametrize("quantity", [0, -1, 2_000_000])
    def test_refuses_a_quantity_that_is_not_a_sane_positive_integer(self, quantity: int) -> None:
        with pytest.raises(AppError) as error:
            calculate_line_total("19.99", quantity)
        assert error.value.code == "INVALID_ITEM_QUANTITY"


class TestOrderTotals:
    def test_sums_the_lines_and_applies_the_discount_before_the_tax(self) -> None:
        totals = calculate_order_totals(["59.97", "10.03"], "5.00", "13.00")

        assert format_scaled_money(totals.subtotal) == "70.00"
        assert format_scaled_money(totals.discount_total) == "5.00"
        assert format_scaled_money(totals.tax_total) == "13.00"
        assert format_scaled_money(totals.total) == "78.00"

    def test_adds_fractions_that_binary_floating_point_cannot(self) -> None:
        assert 0.1 + 0.2 != 0.3

        totals = calculate_order_totals(["0.10", "0.20"], ZERO_MONEY, ZERO_MONEY)
        assert format_scaled_money(totals.subtotal) == "0.30"

    def test_keeps_large_orders_exact(self) -> None:
        totals = calculate_order_totals(["9999999.99"] * 1000, "0", "0")

        assert format_scaled_money(totals.subtotal) == "9999999990.00"

    def test_produces_zero_totals_for_an_order_without_lines(self) -> None:
        totals = calculate_order_totals([], "0", "0")

        assert totals.subtotal == ZERO_MONEY
        assert totals.total == ZERO_MONEY

    def test_rejects_a_discount_that_pushes_the_total_below_zero(self) -> None:
        with pytest.raises(AppError) as error:
            calculate_order_totals(["10.00"], "10.01", "0")

        assert error.value.status_code == 400
        assert error.value.code == "ORDER_TOTALS_INVALID"
        # Reported in the units the client sent, not in cents.
        assert error.value.details == {
            "subtotal": "10.00",
            "discountTotal": "10.01",
            "taxTotal": "0.00",
        }

    def test_lets_the_tax_cover_a_discount_that_alone_would_be_too_large(self) -> None:
        totals = calculate_order_totals(["10.00"], "10.01", "1.00")

        assert format_scaled_money(totals.total) == "0.99"
