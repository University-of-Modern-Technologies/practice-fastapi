"""What the contact endpoints accept, and what they refuse to accept."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.contacts.schemas import (
    ContactListParams,
    CreateContactRequest,
    UpdateContactRequest,
)
from app.modules.contacts.types import ContactSortField


def test_a_contact_must_be_reachable_by_email_or_phone() -> None:
    with pytest.raises(ValidationError):
        CreateContactRequest.model_validate({"firstName": "Ada", "lastName": "Byron"})


def test_an_address_alone_is_enough() -> None:
    payload = CreateContactRequest.model_validate(
        {"firstName": " Ada ", "lastName": "Byron", "email": " Ada@Example.COM "}
    )

    assert payload.email == "ada@example.com"
    assert payload.first_name == "Ada"
    assert payload.phone is None


def test_a_number_alone_is_enough() -> None:
    payload = CreateContactRequest.model_validate(
        {"firstName": "Ada", "lastName": "Byron", "phone": " +380671234567 "}
    )

    assert payload.phone == "+380671234567"
    assert payload.email is None


def test_a_field_the_schema_does_not_declare_is_dropped() -> None:
    # The published contract ignores unknown body fields rather than refusing
    # the request, so a client that sends one gets the same answer from either
    # implementation. What may actually be written is decided by the service,
    # not by the shape of the request.
    payload = CreateContactRequest.model_validate(
        {"firstName": "Ada", "lastName": "Byron", "phone": "+380671234567", "role": "admin"}
    )

    assert not hasattr(payload, "role")
    assert payload.model_fields_set == {"first_name", "last_name", "phone"}


def test_a_patch_with_no_fields_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UpdateContactRequest()


def test_a_patch_distinguishes_an_absent_field_from_an_explicit_null() -> None:
    absent = UpdateContactRequest.model_validate({"company": "Analytical Engines"})
    erased = UpdateContactRequest.model_validate({"company": "Analytical Engines", "email": None})

    # Both carry `email is None`; only the second one asked for it.
    assert "email" not in absent.model_fields_set
    assert "email" in erased.model_fields_set
    assert erased.email is None


def test_a_null_cannot_be_written_into_a_column_that_forbids_it() -> None:
    for field in ("ownerId", "firstName", "lastName"):
        with pytest.raises(ValidationError):
            UpdateContactRequest.model_validate({field: None})


def test_an_owner_may_be_handed_over_by_id() -> None:
    owner_id = uuid.uuid4()

    payload = UpdateContactRequest.model_validate({"ownerId": str(owner_id)})

    assert payload.owner_id == owner_id


def test_a_blank_name_is_not_a_name() -> None:
    with pytest.raises(ValidationError):
        CreateContactRequest.model_validate(
            {"firstName": "   ", "lastName": "Byron", "phone": "+380671234567"}
        )


def test_the_list_query_defaults_to_the_newest_contacts_first() -> None:
    params = ContactListParams()

    assert params.page == 1
    assert params.sort_by is ContactSortField.CREATED_AT
    assert params.sort_order == "desc"
    assert params.offset == 0


def test_an_unknown_sort_column_is_refused() -> None:
    # `sortBy` reaches an ORDER BY clause, so anything outside the enum has to
    # fail at the boundary rather than reach the database.
    with pytest.raises(ValidationError):
        ContactListParams.model_validate({"sortBy": "password"})


def test_the_page_size_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ContactListParams.model_validate({"pageSize": 1000})
