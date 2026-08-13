"""The settings registry as a pure structure — no database, no cache."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import AppError
from app.modules.settings.registry import (
    SETTING_KEYS,
    SETTING_REGISTRY,
    ensure_setting_key,
    is_setting_key,
    parse_setting_value,
    read_stored_value,
    setting_default,
    setting_definition,
)


def test_the_registry_declares_every_known_key() -> None:
    assert SETTING_KEYS == (
        "orders.numberPrefix",
        "organization.defaultCurrency",
        "organization.name",
        "warehouse.defaultCode",
    )


def test_every_key_carries_a_description_and_a_usable_default() -> None:
    for key in SETTING_KEYS:
        definition = setting_definition(key)
        assert definition.description
        # A default that its own declaration rejects would make the key
        # unreadable until somebody wrote a row for it.
        assert parse_setting_value(key, definition.default_value) == definition.default_value


@pytest.mark.parametrize(
    ("key", "candidate", "expected"),
    [
        ("organization.name", "  Acme  ", "Acme"),
        ("organization.defaultCurrency", "eur", "EUR"),
        ("orders.numberPrefix", "inv", "INV"),
        ("warehouse.defaultCode", "north-1", "NORTH-1"),
    ],
)
def test_a_value_is_normalised_as_it_is_accepted(key: str, candidate: Any, expected: Any) -> None:
    assert parse_setting_value(key, candidate) == expected


@pytest.mark.parametrize(
    ("key", "candidate"),
    [
        ("organization.defaultCurrency", "EURO"),
        ("organization.name", 42),
        ("organization.name", ""),
        ("organization.name", None),
        ("orders.numberPrefix", "TOO-LONG-PREFIX"),
        ("warehouse.defaultCode", {"code": "CENTRAL"}),
    ],
)
def test_a_value_that_does_not_fit_its_key_is_refused(key: str, candidate: Any) -> None:
    with pytest.raises(AppError) as error:
        parse_setting_value(key, candidate)

    assert error.value.code == "INVALID_SETTING_VALUE"
    assert error.value.status_code == 400


def test_an_undeclared_key_is_refused_instead_of_being_stored() -> None:
    assert is_setting_key("organization.name") is True
    assert is_setting_key("organization.unknown") is False

    with pytest.raises(AppError) as error:
        ensure_setting_key("organization.unknown")

    assert error.value.code == "UNKNOWN_SETTING_KEY"
    assert error.value.status_code == 400
    assert error.value.details == {"key": "organization.unknown"}


@pytest.mark.parametrize("candidate", ["keys", "items", "__class__", "get"])
def test_a_member_of_the_mapping_itself_is_not_a_key(candidate: str) -> None:
    # The registry is looked up by membership, so an attribute of the container
    # can never be mistaken for a declared setting.
    assert is_setting_key(candidate) is False


def test_every_key_exposes_its_default() -> None:
    assert setting_default("organization.name") == "Training CRM"
    assert setting_default("organization.defaultCurrency") == "USD"
    assert setting_default("orders.numberPrefix") == "ORD"
    # The orders module reads this one, so its default is part of the contract.
    assert setting_default("warehouse.defaultCode") == "CENTRAL"


def test_a_stored_value_that_no_longer_parses_degrades_to_the_default() -> None:
    assert read_stored_value("organization.name", "Stored") == "Stored"
    # A row written before a declaration was tightened must not turn every read
    # into a failure.
    assert read_stored_value("organization.name", {"legacy": True}) == "Training CRM"


def test_the_registry_and_its_sorted_view_hold_the_same_keys() -> None:
    assert set(SETTING_KEYS) == set(SETTING_REGISTRY)
