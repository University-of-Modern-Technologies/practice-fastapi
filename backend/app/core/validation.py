"""Shared request-validation types.

What an API *accepts* is as much a part of its contract as what it returns, and
two backends only stay interchangeable while both draw the boundary in the same
place. Email is where the ecosystems disagree by default: the validator commonly
used here also rejects the reserved domains (``.test``, ``.invalid``,
``.example``) that fixtures and documentation are built on, while the sibling
backend applies a practical pattern and nothing more. A client that succeeds
against one backend and gets a 400 from the other has found a contract break, so
the pattern is pinned here rather than inherited from a library.

Dates are the same story. Left to its defaults the validator reads a number — or
a string of digits — as a Unix timestamp, so ``1704067200`` is accepted as
``2024-01-01`` here and refused by the sibling backend. The types below draw the
line where the sibling backend draws it.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BeforeValidator, WithJsonSchema

__all__ = [
    "EMAIL_PATTERN",
    "ISO_DATE_PATTERN",
    "EmailAddress",
    "IsoAwareDatetime",
    "IsoDate",
    "IsoDatetime",
    "validate_email",
    "validate_iso_date",
    "validate_not_a_timestamp",
]

#: A practical address: no leading dot, no doubled dot, a domain of at least two
#: labels whose last one is alphabetic. Deliverability is deliberately not
#: checked — that is a delivery-time fact, not a request-time one.
EMAIL_PATTERN = re.compile(
    r"^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$"
)


def validate_email(value: str) -> str:
    if not EMAIL_PATTERN.match(value):
        message = "value is not a valid email address"
        raise ValueError(message)
    return value


#: An email address as the API accepts it on the wire.
EmailAddress = Annotated[
    str,
    AfterValidator(validate_email),
    WithJsonSchema({"type": "string", "format": "email"}),
]


#: A calendar date as written on the wire: ``YYYY-MM-DD`` and nothing else —
#: neither a timestamp nor a full date-time that happens to fall on midnight.
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_NOT_AN_ISO_DATE = "Invalid ISO date: expected YYYY-MM-DD"
_NOT_AN_ISO_DATETIME = "Invalid ISO date-time: a numeric timestamp is not accepted"


def validate_iso_date(value: object) -> object:
    """Lets through a ``YYYY-MM-DD`` string, or a date already parsed in code."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and ISO_DATE_PATTERN.fullmatch(value):
        return value  # the calendar itself is checked by the date parser
    raise ValueError(_NOT_AN_ISO_DATE)


def validate_not_a_timestamp(value: object) -> object:
    """Refuses a number, or a string of digits, where a date-time is expected.

    Only the timestamp reading is closed off; every ISO 8601 spelling the date-
    time parser accepts still reaches it.
    """
    if isinstance(value, bool | int | float):
        raise ValueError(_NOT_AN_ISO_DATETIME)
    if isinstance(value, str) and re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", value):
        raise ValueError(_NOT_AN_ISO_DATETIME)
    return value


#: A calendar date on input: ``YYYY-MM-DD`` only, as the sibling backend's
#: ``z.iso.date()``. A Unix timestamp, numeric or as a string, is refused.
IsoDate = Annotated[date, BeforeValidator(validate_iso_date)]

#: An instant on input, refusing the Unix-timestamp reading of a number. The
#: accepted ISO spellings are otherwise the date-time parser's own; a field that
#: needs a narrower grammar adds its own validator on top.
IsoDatetime = Annotated[datetime, BeforeValidator(validate_not_a_timestamp)]

#: An instant that has to carry its UTC offset, with the same refusal of a
#: numeric timestamp.
IsoAwareDatetime = Annotated[AwareDatetime, BeforeValidator(validate_not_a_timestamp)]
