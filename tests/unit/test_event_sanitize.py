"""Redaction of event payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.events.sanitize import CIRCULAR, REDACTED, is_sensitive_event_field, sanitize_event_payload


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "password_hash",
        "passwordHash",
        "token",
        "accessToken",
        "refresh_token",
        "sessionToken",
        "tokenHash",
        "secret",
        "apiKey",
        "api-key",
        "authorization",
        "Authorization",
        "cookie",
    ],
)
def test_sensitive_keys_are_recognised(key: str) -> None:
    assert is_sensitive_event_field(key)


@pytest.mark.parametrize("key", ["email", "id", "passwordPolicy", "tokenizer", "cookies"])
def test_ordinary_keys_are_left_alone(key: str) -> None:
    assert not is_sensitive_event_field(key)


def test_top_level_secrets_are_replaced() -> None:
    payload = {"email": "user@example.com", "password": "hunter2", "token": "abc"}

    assert sanitize_event_payload(payload) == {
        "email": "user@example.com",
        "password": REDACTED,
        "token": REDACTED,
    }


def test_nested_secrets_are_replaced() -> None:
    payload = {"user": {"id": "1", "passwordHash": "$2b$..."}, "headers": {"Cookie": "sid=1"}}

    assert sanitize_event_payload(payload) == {
        "user": {"id": "1", "passwordHash": REDACTED},
        "headers": {"Cookie": REDACTED},
    }


def test_secrets_inside_lists_are_replaced() -> None:
    payload = {"attempts": [{"password": "a"}, {"password": "b"}]}

    assert sanitize_event_payload(payload) == {
        "attempts": [{"password": REDACTED}, {"password": REDACTED}]
    }


def test_cycles_are_broken() -> None:
    payload: dict[str, Any] = {"name": "root"}
    payload["self"] = payload

    assert sanitize_event_payload(payload) == {"name": "root", "self": CIRCULAR}


def test_values_the_store_cannot_hold_are_stringified() -> None:
    payload = {
        "when": datetime(2026, 8, 12, 10, 30, tzinfo=UTC),
        "amount": Decimal("12.50"),
        "id": UUID("00000000-0000-4000-8000-000000000001"),
        "ratio": float("inf"),
        "handle": object(),
    }

    result = sanitize_event_payload(payload)

    assert isinstance(result, dict)
    assert result["when"] == "2026-08-12T10:30:00+00:00"
    assert result["amount"] == "12.5"
    assert result["id"] == "00000000-0000-4000-8000-000000000001"
    assert result["ratio"] == "inf"
    assert isinstance(result["handle"], str)


def test_primitives_pass_through_untouched() -> None:
    assert sanitize_event_payload(None) is None
    assert sanitize_event_payload("plain") == "plain"
    assert sanitize_event_payload(True) is True
    assert sanitize_event_payload(7) == 7


def test_tuples_and_sets_become_lists() -> None:
    assert sanitize_event_payload(("a", "b")) == ["a", "b"]
    assert sanitize_event_payload(frozenset({"a"})) == ["a"]
