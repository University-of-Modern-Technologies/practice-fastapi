"""Order arithmetic.

Every amount is a :class:`~decimal.Decimal` with a fixed scale of two, and no
value ever passes through a ``float``. The reason is exactness: ``0.1 + 0.2`` is
``0.30000000000000004`` in binary floating point and ``19.99 * 7`` is
``139.92999999999998``. Both would be written into a ``Numeric(14, 2)`` column
after a lossy rounding step, and would drift away from the sum a human gets on
paper. ``Decimal`` is exact for decimal fractions, so every intermediate value
is exact and the conversion to a string is a pure formatting step.

The functions here are pure — no session, no models — which is why they are also
the part of the module that can be tested without a database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import AppError
from app.core.serializers import format_scaled_money, quantize_money
from app.modules.orders.types import (
    INVALID_ITEM_QUANTITY,
    INVALID_MONETARY_AMOUNT,
    ORDER_TOTALS_INVALID,
)

__all__ = [
    "MAX_ITEM_QUANTITY",
    "MONEY_SCALE",
    "MONEY_STRING_PATTERN",
    "ZERO_MONEY",
    "OrderTotals",
    "calculate_line_total",
    "calculate_order_totals",
    "normalize_money",
]

#: Number of decimal places of the monetary columns (``Numeric(14, 2)``).
MONEY_SCALE = 2

#: Digits available in front of the decimal point, from the same column type.
MONEY_PRECISION = 12

#: Shape a monetary amount must have on the wire; reused by the schemas.
MONEY_STRING_PATTERN = r"^\d{1,12}(?:\.\d{1,2})?$"

#: Upper bound on a single line, so one typo cannot allocate a warehouse.
MAX_ITEM_QUANTITY = 1_000_000

ZERO_MONEY = Decimal("0.00")

_MONEY_STRING = re.compile(MONEY_STRING_PATTERN)
_MONEY_LIMIT = Decimal(10) ** MONEY_PRECISION


def _reject(value: object) -> AppError:
    return AppError(f"Invalid monetary amount: {value}", 400, INVALID_MONETARY_AMOUNT)


def normalize_money(value: Decimal | str) -> Decimal:
    """Validates an amount and pins it to exactly two decimal places.

    Accepts both representations the module meets: the string a client sends,
    and the ``Decimal`` the driver hands back — the database renders
    ``Numeric(14, 2)`` without trailing zeros, so ``19.9`` and ``19.90`` arrive
    as the same amount and must leave as the same string.
    """
    if isinstance(value, str):
        candidate = value.strip()
        if not _MONEY_STRING.fullmatch(candidate):
            raise _reject(value)
        return quantize_money(Decimal(candidate))

    if not value.is_finite() or value < 0 or value >= _MONEY_LIMIT:
        raise _reject(value)
    exponent = value.as_tuple().exponent
    # An amount with more than two decimals is a rounding decision the caller
    # has to make explicitly; silently rounding it here would lose a cent.
    if not isinstance(exponent, int) or exponent < -MONEY_SCALE:
        raise _reject(value)
    return quantize_money(value)


def _validate_quantity(quantity: int) -> int:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise AppError("Quantity must be a positive integer", 400, INVALID_ITEM_QUANTITY)
    if quantity <= 0 or quantity > MAX_ITEM_QUANTITY:
        raise AppError("Quantity must be a positive integer", 400, INVALID_ITEM_QUANTITY)
    return quantity


def calculate_line_total(unit_price: Decimal | str, quantity: int) -> Decimal:
    """Price of one line: the snapshot unit price times the ordered quantity."""
    return quantize_money(normalize_money(unit_price) * _validate_quantity(quantity))


@dataclass(frozen=True, slots=True)
class OrderTotals:
    """The four monetary fields of an order, all derived from its lines."""

    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal


def calculate_order_totals(
    line_totals: Iterable[Decimal | str],
    discount_total: Decimal | str,
    tax_total: Decimal | str,
) -> OrderTotals:
    """Recomputes every monetary field of an order from its lines.

    A client-supplied total is never trusted, so this is the only place order
    totals originate: the discount comes off the sum of the lines, and the tax
    goes on top of what is left.
    """
    subtotal = ZERO_MONEY
    for line_total in line_totals:
        subtotal += normalize_money(line_total)

    discount = normalize_money(discount_total)
    tax = normalize_money(tax_total)
    total = subtotal - discount + tax
    if total < 0:
        raise AppError(
            "Order discount exceeds the order value",
            400,
            ORDER_TOTALS_INVALID,
            # Reported in the units the client sent, not in cents.
            {
                "subtotal": format_scaled_money(subtotal),
                "discountTotal": format_scaled_money(discount),
                "taxTotal": format_scaled_money(tax),
            },
        )
    return OrderTotals(
        subtotal=quantize_money(subtotal),
        discount_total=discount,
        tax_total=tax,
        total=quantize_money(total),
    )
