"""The audit trail is read by people investigating incidents, so what it must
never contain is worth testing directly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import pytest

from app.modules.audit.sanitize import (
    CIRCULAR,
    REDACTED,
    is_sensitive_audit_field,
    sanitize_audit_value,
)


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "passwordHash",
        "password_hash",
        "PASSWORD-HASH",
        "token",
        "refreshToken",
        "authorization",
        "Cookie",
        "apiKey",
        "sessionToken",
        "secret",
        "tokenHash",
    ],
)
def test_credential_keys_are_recognised(key: str) -> None:
    assert is_sensitive_audit_field(key)


@pytest.mark.parametrize("key", ["email", "name", "ownerId", "stage", "amount", "passenger"])
def test_ordinary_keys_are_left_alone(key: str) -> None:
    assert not is_sensitive_audit_field(key)


def test_credentials_are_replaced_at_any_depth() -> None:
    payload = {
        "email": "user@example.com",
        "password": "hunter2",
        "nested": {"refresh_token": "abc", "keep": 1},
        "list": [{"apiKey": "xyz"}],
    }

    result = sanitize_audit_value(payload)

    assert result == {
        "email": "user@example.com",
        "password": REDACTED,
        "nested": {"refresh_token": REDACTED, "keep": 1},
        "list": [{"apiKey": REDACTED}],
    }


def test_uuid_and_timestamp_survive_as_strings() -> None:
    identifier = uuid.uuid4()
    moment = datetime(2026, 8, 12, 15, 23, 45, 123_456, tzinfo=UTC)

    result = sanitize_audit_value({"id": identifier, "at": moment})

    assert result == {"id": str(identifier), "at": "2026-08-12T15:23:45.123Z"}


def test_decimal_takes_the_wire_form_of_an_amount() -> None:
    # An amount reads the same in the trail as in the response it records, so
    # the padding of the column does not survive into the entry either.
    assert sanitize_audit_value({"amount": Decimal("1234.50")}) == {"amount": "1234.5"}
    assert sanitize_audit_value({"amount": Decimal("2400.00")}) == {"amount": "2400"}


def test_enum_is_reduced_to_its_value() -> None:
    class Stage(StrEnum):
        LEAD = "LEAD"

    assert sanitize_audit_value({"stage": Stage.LEAD}) == {"stage": "LEAD"}


def test_a_cycle_does_not_hang() -> None:
    payload: dict[str, Any] = {"name": "root"}
    payload["self"] = payload

    assert sanitize_audit_value(payload) == {"name": "root", "self": CIRCULAR}


def test_non_finite_numbers_become_text() -> None:
    result = sanitize_audit_value({"ratio": float("inf"), "missing": float("nan")})

    assert result["ratio"] == "inf"
    assert result["missing"] == "nan"


def test_tuples_and_sets_become_lists() -> None:
    assert sanitize_audit_value({"pair": (1, 2)}) == {"pair": [1, 2]}
    assert sanitize_audit_value({"one": {"only"}}) == {"one": ["only"]}


def test_unknown_objects_are_stringified_rather_than_dropped() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    assert sanitize_audit_value({"thing": Opaque()}) == {"thing": "opaque"}
