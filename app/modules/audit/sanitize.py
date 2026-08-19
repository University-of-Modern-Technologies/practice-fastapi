"""Redaction of audit payloads.

The trail is read by people investigating what happened, which makes it exactly
the wrong place for a credential to survive. Domain modules therefore hand over
whatever describes their change and this module decides what is safe to keep.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.core.serializers import format_datetime, format_money

REDACTED = "[REDACTED]"
CIRCULAR = "[CIRCULAR]"

# Compared after stripping every non-alphanumeric character and lowercasing, so
# `passwordHash`, `password_hash` and `PASSWORD-HASH` all collapse to one entry.
SENSITIVE_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "passwordhash",
        "refreshtoken",
        "secret",
        "sessiontoken",
        "token",
        "tokenhash",
    }
)

_NON_ALPHANUMERIC = re.compile(r"[^a-zA-Z0-9]")

#: Guards against a payload deep enough to be a mistake rather than data.
MAX_DEPTH = 12

# Ordered, because the checks are `isinstance`: `bool` before `int` and
# `datetime` before `date`, since each is a subclass of the one after it.
_SCALARS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (bool, lambda value: value),
    (str, lambda value: value),
    (int, lambda value: value),
    # NaN and the infinities have no JSON representation.
    (float, lambda value: value if math.isfinite(value) else str(value)),
    # The same wire form a monetary field gets, so an amount reads the
    # same in the trail as in the response it records.
    (Decimal, format_money),
    (uuid.UUID, str),
    (datetime, format_datetime),
    (date, lambda value: value.isoformat()),
)

_MISSING = object()


def normalise_key(key: str) -> str:
    return _NON_ALPHANUMERIC.sub("", key).lower()


def is_sensitive_audit_field(key: str) -> bool:
    return normalise_key(key) in SENSITIVE_KEYS


def _as_scalar(candidate: Any) -> Any:
    """Converts a leaf value, or returns the sentinel if it is not one."""
    for kind, converter in _SCALARS:
        if isinstance(candidate, kind):
            return converter(candidate)
    return _MISSING


def sanitize_audit_value(value: Any) -> Any:
    """Returns a JSON-safe copy with every credential replaced.

    Types the database cannot store are converted rather than dropped: a UUID
    and a timestamp are the two things an audit entry most often carries, and
    losing them would make the record useless.
    """
    seen: set[int] = set()

    def convert(candidate: Any, depth: int) -> Any:
        if candidate is None:
            return None

        scalar = _as_scalar(candidate)
        if scalar is not _MISSING:
            return scalar

        if isinstance(candidate, Enum):
            return convert(candidate.value, depth)

        if depth > MAX_DEPTH:
            return str(candidate)

        if isinstance(candidate, dict | list | tuple | set | frozenset):
            return convert_container(candidate, depth)

        return str(candidate)

    def convert_container(candidate: Any, depth: int) -> Any:
        # A payload assembled from live ORM objects can easily contain a cycle;
        # recording the marker keeps the write from hanging.
        if id(candidate) in seen:
            return CIRCULAR
        seen.add(id(candidate))

        if isinstance(candidate, dict):
            return {
                str(key): REDACTED
                if is_sensitive_audit_field(str(key))
                else convert(item, depth + 1)
                for key, item in candidate.items()
            }
        return [convert(item, depth + 1) for item in candidate]

    return convert(value, 0)
