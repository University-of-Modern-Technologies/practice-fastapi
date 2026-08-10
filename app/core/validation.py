"""Shared request-validation types.

What an API *accepts* is as much a part of its contract as what it returns, and
two backends only stay interchangeable while both draw the boundary in the same
place. Email is where the ecosystems disagree by default: the validator commonly
used here also rejects the reserved domains (``.test``, ``.invalid``,
``.example``) that fixtures and documentation are built on, while the sibling
backend applies a practical pattern and nothing more. A client that succeeds
against one backend and gets a 400 from the other has found a contract break, so
the pattern is pinned here rather than inherited from a library.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, WithJsonSchema

__all__ = ["EMAIL_PATTERN", "EmailAddress", "validate_email"]

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
