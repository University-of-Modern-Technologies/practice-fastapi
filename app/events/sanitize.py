"""Payload redaction.

An event payload is assembled from whatever the domain module had at hand, which
means a request body or a user row can end up inside it by accident. The log is
append-only and long-lived, so a secret written here is a secret that stays for
the whole retention window: redaction happens on the way in, unconditionally.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.serializers import format_money
from app.events.types import EventJsonValue

REDACTED = "[REDACTED]"
CIRCULAR = "[CIRCULAR]"

# Compared against the key with every separator removed, so `password_hash`,
# `passwordHash` and `PASSWORD-HASH` all collapse onto one entry.
_SENSITIVE_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "cookie",
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


def _normalise_key(key: str) -> str:
    return _NON_ALPHANUMERIC.sub("", key).lower()


def is_sensitive_event_field(key: str) -> bool:
    return _normalise_key(key) in _SENSITIVE_KEYS


def _sanitize_scalar(candidate: Any) -> EventJsonValue:
    if candidate is None or isinstance(candidate, str | bool | int):
        return candidate
    if isinstance(candidate, float):
        # NaN and the infinities have no JSON spelling.
        return candidate if math.isfinite(candidate) else str(candidate)
    if isinstance(candidate, datetime | date):
        return candidate.isoformat()
    if isinstance(candidate, Decimal):
        # The same wire form a monetary field gets, rather than the padded text
        # the type happens to print.
        return format_money(candidate)
    # UUIDs, model instances, exceptions: whatever it was, its text form is the
    # only thing the log can meaningfully keep.
    return str(candidate)


def _sanitize_mapping(candidate: dict[Any, Any], seen: set[int]) -> EventJsonValue:
    if id(candidate) in seen:
        return CIRCULAR
    seen.add(id(candidate))
    return {
        str(key): REDACTED if is_sensitive_event_field(str(key)) else _sanitize(item, seen)
        for key, item in candidate.items()
    }


def _sanitize_sequence(candidate: Any, seen: set[int]) -> EventJsonValue:
    if id(candidate) in seen:
        return CIRCULAR
    seen.add(id(candidate))
    return [_sanitize(item, seen) for item in candidate]


def _sanitize(candidate: Any, seen: set[int]) -> EventJsonValue:
    if isinstance(candidate, dict):
        return _sanitize_mapping(candidate, seen)
    if isinstance(candidate, list | tuple | set | frozenset):
        return _sanitize_sequence(candidate, seen)
    return _sanitize_scalar(candidate)


def sanitize_event_payload(value: Any) -> EventJsonValue:
    """Deep, case-insensitive redaction of secrets before an event is stored.

    Mappings and sequences are traversed, cycles are broken, and anything the
    document store could not represent is stringified — so the result is always
    safe to serialise, whatever the caller passed.
    """
    return _sanitize(value, set())
