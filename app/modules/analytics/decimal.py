"""Exact decimal arithmetic for reports.

Money never travels through a float in this module. Values arrive either as a
``Decimal`` read from a ``Numeric(14, 2)`` column or as a string produced by the
database, and every conversion below is integer arithmetic on the digits, so no
cent is ever lost to binary rounding. The public helpers therefore return money
as fixed-scale decimal strings.

Rounding is *half away from zero* everywhere: ``0.005`` becomes ``0.01`` and
``-0.005`` becomes ``-0.01``. That is the rule the sibling backend applies, and a
report that rounded differently would disagree with it by a cent on exactly the
values a reader is most likely to check by hand.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from decimal import Decimal

__all__ = [
    "MONEY_SCALE",
    "DecimalInput",
    "average_decimal",
    "compare_decimals",
    "format_decimal",
    "from_scaled_integer",
    "ratio",
    "sum_decimals",
    "to_scaled_integer",
]

#: Number of fractional digits used for every monetary value.
MONEY_SCALE = 2

#: Anything a report may be handed as an amount, including the empty aggregate a
#: ``SUM`` over no rows produces.
type DecimalInput = Decimal | str | int | float | None

#: Only a plain decimal literal is arithmetic here. Exponent forms, currency
#: symbols and thousands separators are deliberately outside the grammar.
_PLAIN_DECIMAL = re.compile(r"^-?\d+(?:\.\d+)?$")

#: Rounding boundary, compared as a character so the fraction is never parsed.
_DIGIT_FIVE = "5"

#: Denominator of a rate: four decimal places, as ``ratio`` documents.
_RATE_PRECISION = 10_000


def _raw_text(value: DecimalInput) -> str:
    """Renders any accepted input as the text its digits live in."""
    if value is None:
        return "0"
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def to_scaled_integer(value: DecimalInput, scale: int = MONEY_SCALE) -> int:
    """Converts a decimal value into a whole number of the smallest unit.

    Cents at the default scale, rounded half away from zero. Anything that is
    not a plain decimal literal — an empty aggregate, an exponent form — counts
    as zero, which keeps a single odd row from failing a whole report.
    """
    text = _raw_text(value)
    if _PLAIN_DECIMAL.match(text) is None:
        return 0

    negative = text.startswith("-")
    digits = text[1:] if negative else text
    integer_part, _, fraction_part = digits.partition(".")

    kept = fraction_part[:scale].ljust(scale, "0")
    scaled = int(f"{integer_part}{kept}")
    if len(fraction_part) > scale and fraction_part[scale] >= _DIGIT_FIVE:
        scaled += 1

    return -scaled if negative else scaled


def from_scaled_integer(value: int, scale: int = MONEY_SCALE) -> str:
    """Renders a whole number of smallest units back as a fixed-scale string."""
    negative = value < 0
    digits = str(-value if negative else value).rjust(scale + 1, "0")
    cut = len(digits) - scale
    text = digits if scale == 0 else f"{digits[:cut]}.{digits[cut:]}"
    return f"-{text}" if negative else text


def format_decimal(value: DecimalInput, scale: int = MONEY_SCALE) -> str:
    """Normalises any decimal input to a fixed-scale string, e.g. ``1234.50``."""
    return from_scaled_integer(to_scaled_integer(value, scale), scale)


def average_decimal(total: DecimalInput, count: int, scale: int = MONEY_SCALE) -> str:
    """Averages a decimal total over a count, rounding half away from zero.

    A zero count yields a zero string rather than a division by zero.
    """
    if count <= 0:
        return from_scaled_integer(0, scale)
    scaled = to_scaled_integer(total, scale)
    divisor = math.trunc(count)
    negative = scaled < 0
    magnitude = -scaled if negative else scaled
    # Adding half the divisor before an integer division is the exact form of
    # "round half up" without a float ever appearing.
    rounded = (magnitude * 2 + divisor) // (divisor * 2)
    return from_scaled_integer(-rounded if negative else rounded, scale)


def sum_decimals(values: Sequence[DecimalInput], scale: int = MONEY_SCALE) -> str:
    """Sums decimal inputs without ever leaving exact integer arithmetic."""
    total = sum(to_scaled_integer(value, scale) for value in values)
    return from_scaled_integer(total, scale)


def compare_decimals(
    left: DecimalInput,
    right: DecimalInput,
    scale: int = MONEY_SCALE,
) -> int:
    """Orders two decimal values without converting either to a float."""
    first = to_scaled_integer(left, scale)
    second = to_scaled_integer(right, scale)
    if first == second:
        return 0
    return -1 if first < second else 1


def ratio(numerator: int, denominator: int) -> float:
    """Ratio between two counts, rounded to four decimal places.

    This is a rate, not money, so a plain number is the right shape. A zero
    denominator yields ``0`` instead of a division error or an infinity.
    """
    if denominator <= 0:
        return 0.0
    # `math.floor(x + 0.5)` rather than `round`: the built-in rounds halves to
    # the nearest even number, which would report a different rate than the
    # sibling backend on exactly the values that end in a five.
    scaled = math.floor(numerator / denominator * _RATE_PRECISION + 0.5)
    return scaled / _RATE_PRECISION
