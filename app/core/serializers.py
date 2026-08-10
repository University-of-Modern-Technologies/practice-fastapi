"""Shared field types that pin the wire format.

Two backends serve the same client, so the JSON representation of a timestamp
and of a monetary amount cannot be left to library defaults: the defaults differ
between ecosystems and the difference is invisible until a client breaks on it.
Both formats are therefore defined once, here, and reused through annotated
types rather than repeated per field.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema
from pydantic.alias_generators import to_camel

__all__ = [
    "Money",
    "UtcDate",
    "UtcDatetime",
    "format_date",
    "format_datetime",
    "format_money",
    "format_scaled_money",
    "quantize_money",
    "to_camel",
]

MONEY_EXPONENT = Decimal("0.01")


def format_datetime(value: datetime) -> str:
    """Renders an instant as UTC with exactly three fractional digits.

    A naive value is read as UTC rather than as local time: every timestamp in
    this system originates from a ``timestamptz`` column, so a missing tzinfo
    means the driver dropped it, not that the instant is local.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    moment = aware.astimezone(UTC)
    milliseconds = moment.microsecond // 1000
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{milliseconds:03d}Z"


def quantize_money(value: Decimal) -> Decimal:
    """Normalises an amount to exactly two decimal places."""
    return value.quantize(MONEY_EXPONENT, rounding=ROUND_HALF_UP)


def format_scaled_money(value: Decimal) -> str:
    """Renders an amount padded to exactly two decimals, e.g. ``"12.50"``.

    Used where the contract asks for a fixed scale — report figures and the
    monetary details of an error — never for a persisted amount on the wire.
    """
    return f"{quantize_money(value):f}"


def format_money(value: Decimal) -> str:
    """Renders a persisted amount as its shortest exact decimal string.

    Amounts travel as strings because the client runs on a language whose only
    number type cannot hold them exactly. The *shape* of that string is not a
    free choice: the sibling backend renders a stored amount through its decimal
    library, which drops trailing zeros, so ``12.50`` reaches the client as
    ``"12.5"``, ``2400.00`` as ``"2400"`` and ``0.00`` as ``"0"``. Padding to a
    fixed scale here would disagree with it on every monetary field.

    ``normalize`` is what strips the zeros, and it is also what makes an
    exponent possible: ``Decimal("2400.00").normalize()`` is ``2.4E+3``. The
    ``f`` presentation is therefore mandatory — it renders positional notation
    at every magnitude, which is what the other backend emits and what a client
    parsing a decimal string can read.
    """
    return f"{value.normalize():f}"


#: Timestamp rendered as ``2026-08-12T15:23:45.123Z``.
#:
#: The JSON Schema override only documents what the serialiser already does:
#: the published contract marks every timestamp ``format: date-time``, and a
#: bare ``string`` would under-describe the field for a generated client.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(format_datetime, return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


def format_date(value: date) -> str:
    """Renders a calendar date as the instant that starts it, in UTC.

    The column behind such a field holds a bare ``date``, but on the wire the
    contract carries a full timestamp: the client reads every temporal field
    with the same parser, so a date-only string would be the one value it has to
    special-case. ``2026-12-31`` therefore leaves as ``2026-12-31T00:00:00.000Z``.
    """
    return f"{value.isoformat()}T00:00:00.000Z"


#: Calendar date rendered as the instant that starts it, e.g.
#: ``2026-08-12T00:00:00.000Z``. The JSON Schema override keeps the published
#: contract honest: the field is documented as a timestamp, not as a date.
UtcDate = Annotated[
    date,
    PlainSerializer(format_date, return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]

#: Persisted monetary amount, rendered in shortest exact form, e.g. ``"1234.5"``.
Money = Annotated[Decimal, PlainSerializer(format_money, return_type=str)]
