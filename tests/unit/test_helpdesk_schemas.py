"""The wire contract of the helpdesk endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.enums import TicketChannel, TicketPriority, TicketStatus
from app.modules.helpdesk.schemas import (
    CreateTicketRequest,
    TicketListParams,
    TicketOut,
    TransitionTicketRequest,
    UpdateTicketRequest,
)
from app.modules.helpdesk.types import MAX_BODY_LENGTH, MAX_NOTE_LENGTH, MAX_SUBJECT_LENGTH

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)

MINIMAL_CREATE: dict[str, Any] = {
    "subject": "Cannot sign in",
    "body": "The password reset link expires before it arrives.",
    "channel": "EMAIL",
}


def make_ticket_out(**overrides: Any) -> TicketOut:
    payload: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": "TKT-00000042",
        "subject": "Cannot sign in",
        "body": "The password reset link expires before it arrives.",
        "channel": TicketChannel.EMAIL,
        "status": TicketStatus.NEW,
        "priority": TicketPriority.NORMAL,
        "contact_id": None,
        "assignee_id": None,
        "owner_id": uuid.uuid4(),
        "opened_at": NOW,
        "resolved_at": None,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return TicketOut(**(payload | overrides))


def test_a_ticket_is_published_in_the_agreed_field_order() -> None:
    payload = make_ticket_out().model_dump(by_alias=True)

    assert list(payload) == [
        "id",
        "number",
        "subject",
        "body",
        "channel",
        "status",
        "priority",
        "ownerId",
        "contactId",
        "assigneeId",
        "version",
        "openedAt",
        "resolvedAt",
        "createdAt",
        "updatedAt",
    ]


def test_a_soft_deleted_flag_never_reaches_the_wire() -> None:
    assert "deletedAt" not in make_ticket_out().model_dump(by_alias=True)


def test_timestamps_travel_in_the_shape_both_backends_emit() -> None:
    payload = make_ticket_out(resolved_at=NOW).model_dump(by_alias=True)

    assert payload["openedAt"] == "2026-08-12T15:23:45.123Z"
    assert payload["resolvedAt"] == "2026-08-12T15:23:45.123Z"


def test_an_unresolved_ticket_publishes_a_null_resolution_moment() -> None:
    assert make_ticket_out().model_dump(by_alias=True)["resolvedAt"] is None


def test_a_new_ticket_needs_a_subject_a_body_and_a_channel() -> None:
    request = CreateTicketRequest.model_validate(MINIMAL_CREATE)

    assert request.subject == "Cannot sign in"
    assert request.channel is TicketChannel.EMAIL
    # Neither is decided here: the server picks the owner and the priority.
    assert request.owner_id is None
    assert request.priority is None


@pytest.mark.parametrize("missing", ["subject", "body", "channel"])
def test_a_new_ticket_without_one_of_the_required_fields_is_rejected(missing: str) -> None:
    payload = {key: value for key, value in MINIMAL_CREATE.items() if key != missing}

    with pytest.raises(ValidationError):
        CreateTicketRequest.model_validate(payload)


def test_surrounding_whitespace_is_stripped_from_the_text_fields() -> None:
    request = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"subject": "  Cannot sign in  "})

    assert request.subject == "Cannot sign in"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject", ""),
        ("subject", "   "),
        ("subject", "x" * (MAX_SUBJECT_LENGTH + 1)),
        ("body", ""),
        ("body", "x" * (MAX_BODY_LENGTH + 1)),
    ],
)
def test_text_the_column_cannot_hold_is_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        CreateTicketRequest.model_validate(MINIMAL_CREATE | {field: value})


def test_a_ticket_may_not_be_opened_past_the_start_of_the_lifecycle() -> None:
    request = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"status": "RESOLVED"})

    # The field is absent from the shape entirely: a ticket always opens as
    # NEW, so there is nothing for the client to state.
    assert not hasattr(request, "status")


def test_the_number_is_not_the_clients_to_choose() -> None:
    request = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"number": "TKT-00000001"})

    # Allocated by the server, so a value sent here has nowhere to land.
    assert not hasattr(request, "number")


def test_an_update_cannot_set_the_status() -> None:
    request = UpdateTicketRequest.model_validate(
        {"version": 1, "subject": "Renamed", "status": "CLOSED"}
    )

    # The lifecycle is advanced by one endpoint only; an edit that could set
    # the status would make the whole machine decorative. The field is absent
    # from the shape, so a value sent here has nowhere to land.
    assert not hasattr(request, "status")
    assert "status" not in request.model_fields_set


def test_an_update_that_names_only_the_status_asks_for_nothing_at_all() -> None:
    # `status` is dropped before the "at least one field" rule runs, so a body
    # carrying nothing else is refused rather than silently applied as a no-op.
    with pytest.raises(ValidationError):
        UpdateTicketRequest.model_validate({"version": 1, "status": "CLOSED"})


def test_an_update_has_to_ask_for_something() -> None:
    with pytest.raises(ValidationError):
        UpdateTicketRequest.model_validate({"version": 1})


def test_an_update_tells_an_absent_field_from_an_explicit_null() -> None:
    cleared = UpdateTicketRequest.model_validate({"version": 1, "contactId": None})
    untouched = UpdateTicketRequest.model_validate({"version": 1, "subject": "Renamed"})

    assert "contact_id" in cleared.model_fields_set
    assert cleared.contact_id is None
    assert "contact_id" not in untouched.model_fields_set


@pytest.mark.parametrize("field", ["ownerId", "channel", "priority"])
def test_a_null_on_a_column_that_cannot_hold_one_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        UpdateTicketRequest.model_validate({"version": 1, field: None})


@pytest.mark.parametrize("version", [0, -1, "abc"])
def test_an_update_without_a_usable_version_is_refused(version: object) -> None:
    with pytest.raises(ValidationError):
        UpdateTicketRequest.model_validate({"version": version, "subject": "Renamed"})


def test_a_transition_carries_a_target_and_the_version_it_was_read_at() -> None:
    request = TransitionTicketRequest.model_validate({"toStatus": "OPEN", "version": 3})

    assert request.to_status is TicketStatus.OPEN
    assert request.version == 3
    assert request.note is None


def test_a_transition_note_is_trimmed_and_bounded() -> None:
    request = TransitionTicketRequest.model_validate(
        {"toStatus": "OPEN", "version": 1, "note": "  picked up  "}
    )
    assert request.note == "picked up"

    with pytest.raises(ValidationError):
        TransitionTicketRequest.model_validate(
            {"toStatus": "OPEN", "version": 1, "note": "x" * (MAX_NOTE_LENGTH + 1)}
        )


def test_a_transition_to_something_outside_the_enum_is_refused() -> None:
    with pytest.raises(ValidationError):
        TransitionTicketRequest.model_validate({"toStatus": "ARCHIVED", "version": 1})


def test_the_list_defaults_match_the_shared_pagination_contract() -> None:
    params = TicketListParams.model_validate({})

    assert params.page == 1
    assert params.page_size == 20
    assert params.sort_by == "createdAt"
    assert params.sort_order == "desc"


@pytest.mark.parametrize("sort_by", ["createdAt", "updatedAt", "openedAt", "priority", "status"])
def test_every_published_sort_column_is_accepted(sort_by: str) -> None:
    assert TicketListParams.model_validate({"sortBy": sort_by}).sort_by == sort_by


@pytest.mark.parametrize("sort_by", ["subject", "number", "tickets.id; DROP TABLE"])
def test_a_column_outside_the_published_set_never_reaches_an_order_by(sort_by: str) -> None:
    with pytest.raises(ValidationError):
        TicketListParams.model_validate({"sortBy": sort_by})


def test_a_page_larger_than_the_ceiling_is_refused() -> None:
    with pytest.raises(ValidationError):
        TicketListParams.model_validate({"pageSize": 101})


def test_the_published_filters_are_all_accepted() -> None:
    contact_id = uuid.uuid4()
    params = TicketListParams.model_validate(
        {
            "status": "OPEN",
            "channel": "CHAT",
            "priority": "URGENT",
            "contactId": str(contact_id),
            "assigneeId": str(uuid.uuid4()),
            "ownerId": str(uuid.uuid4()),
            "openedFrom": "2026-08-01T00:00:00Z",
            "openedTo": "2026-08-31T00:00:00Z",
        }
    )

    assert params.status is TicketStatus.OPEN
    assert params.channel is TicketChannel.CHAT
    assert params.priority is TicketPriority.URGENT
    assert params.contact_id == contact_id
    assert params.opened_from == datetime(2026, 8, 1, tzinfo=UTC)


def test_a_query_string_picked_up_on_the_way_through_a_browser_is_ignored() -> None:
    params = TicketListParams.model_validate({"utm_source": "newsletter", "_": "1723471425"})

    assert params.page == 1
