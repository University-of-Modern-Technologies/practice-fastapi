"""The wire contract of the call endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.enums import CallDirection, CallDisposition
from app.modules.calls.schemas import (
    CallListParams,
    CallOut,
    CallRecordingOut,
    LinkCallRequest,
    SyncCallsOut,
    UpdateCallRequest,
)
from app.modules.calls.types import MAX_NOTES_LENGTH

NOW = datetime(2026, 9, 1, 8, 0, 0, 123_000, tzinfo=UTC)
LATER = datetime(2026, 9, 2, 8, 0, 0, tzinfo=UTC)


def make_call_out(**overrides: Any) -> CallOut:
    payload: dict[str, Any] = {
        "id": uuid.uuid4(),
        "external_id": "stub-call-0000",
        "direction": CallDirection.INBOUND,
        "disposition": CallDisposition.ANSWERED,
        "from_number": "+380671230001",
        "to_number": "+380442001010",
        "started_at": NOW,
        "duration_seconds": 45,
        "contact_id": None,
        "deal_id": None,
        "owner_id": None,
        "recording_url": None,
        "notes": None,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return CallOut(**(payload | overrides))


# --- the published shape --------------------------------------------------


def test_a_call_is_published_in_the_agreed_field_order() -> None:
    payload = make_call_out().model_dump(by_alias=True)

    assert list(payload) == [
        "id",
        "externalId",
        "direction",
        "disposition",
        "fromNumber",
        "toNumber",
        "startedAt",
        "durationSeconds",
        "contactId",
        "dealId",
        "ownerId",
        "recordingUrl",
        "notes",
        "version",
        "createdAt",
        "updatedAt",
    ]


def test_the_soft_delete_flag_never_reaches_the_wire() -> None:
    # A deleted call does not leave the service at all, so the field would only
    # ever be null on the wire.
    assert "deletedAt" not in make_call_out().model_dump(by_alias=True)


def test_every_association_may_be_absent() -> None:
    # The whole module rests on this: a call arrives before anybody has decided
    # what it belongs to, and that is a normal record rather than a broken one.
    published = make_call_out().model_dump(by_alias=True)

    assert published["contactId"] is None
    assert published["dealId"] is None
    assert published["ownerId"] is None


def test_timestamps_are_published_in_the_agreed_notation() -> None:
    published = make_call_out().model_dump(by_alias=True, mode="json")

    assert published["startedAt"] == "2026-09-01T08:00:00.123Z"


def test_a_recording_link_carries_the_moment_it_stops_working() -> None:
    published = CallRecordingOut(url="https://recordings.invalid/a.mp3", expires_at=NOW).model_dump(
        by_alias=True, mode="json"
    )

    assert list(published) == ["url", "expiresAt"]
    assert published["expiresAt"] == "2026-09-01T08:00:00.123Z"


def test_a_sync_reports_three_counts_under_the_agreed_names() -> None:
    published = SyncCallsOut(fetched=24, created=0, skipped=24).model_dump(by_alias=True)

    assert published == {"fetched": 24, "created": 0, "skipped": 24}


# --- updating -------------------------------------------------------------


def test_an_update_must_ask_for_something_beyond_the_version() -> None:
    with pytest.raises(ValidationError):
        UpdateCallRequest.model_validate({"version": 1})


def test_an_update_may_clear_an_association() -> None:
    # Null is a value in its own right here: an operator who linked the wrong
    # customer has to be able to undo it.
    data = UpdateCallRequest.model_validate({"version": 2, "contactId": None})

    assert "contact_id" in data.model_fields_set
    assert data.contact_id is None


def test_an_update_cannot_rewrite_the_providers_own_facts() -> None:
    # Direction, numbers and duration describe traffic that already happened.
    # They are absent from the shape, so an attempt to send one is simply not
    # an update of anything.
    data = UpdateCallRequest.model_validate(
        {"version": 1, "notes": "Call-back agreed", "direction": "OUTBOUND", "durationSeconds": 1}
    )

    assert data.model_fields_set == {"version", "notes"}
    assert not hasattr(data, "direction")


def test_notes_are_trimmed_and_bounded() -> None:
    data = UpdateCallRequest.model_validate({"version": 1, "notes": "  wrong number  "})
    assert data.notes == "wrong number"

    with pytest.raises(ValidationError):
        UpdateCallRequest.model_validate({"version": 1, "notes": "x" * (MAX_NOTES_LENGTH + 1)})


def test_a_version_below_one_is_refused() -> None:
    with pytest.raises(ValidationError):
        UpdateCallRequest.model_validate({"version": 0, "notes": "x"})


# --- linking --------------------------------------------------------------


def test_a_link_must_name_at_least_one_target() -> None:
    # A request that names neither would burn a version and announce a
    # `call.linked` that linked nothing.
    with pytest.raises(ValidationError):
        LinkCallRequest.model_validate({"version": 1})


@pytest.mark.parametrize("field", ["contactId", "dealId"])
def test_either_target_on_its_own_is_enough(field: str) -> None:
    data = LinkCallRequest.model_validate({"version": 1, field: str(uuid.uuid4())})

    assert data.version == 1


@pytest.mark.parametrize("field", ["contactId", "dealId"])
def test_a_link_refuses_an_explicit_null(field: str) -> None:
    # This endpoint has one direction by design: detaching is an edit, and
    # goes through PATCH, where null already means "clear it".
    with pytest.raises(ValidationError):
        LinkCallRequest.model_validate({"version": 1, field: None})


def test_a_link_naming_one_target_and_nulling_the_other_is_refused() -> None:
    with pytest.raises(ValidationError):
        LinkCallRequest.model_validate(
            {"version": 1, "contactId": str(uuid.uuid4()), "dealId": None}
        )


# --- browsing -------------------------------------------------------------


def test_the_call_log_is_ordered_by_when_people_spoke_by_default() -> None:
    params = CallListParams()

    assert params.sort_by == "startedAt"
    assert params.sort_order == "desc"
    assert params.page == 1


def test_an_unzoned_window_bound_is_refused() -> None:
    # "2026-09-01T00:00:00" means a different instant in every office that
    # sends it; reading it as UTC would answer a question nobody asked.
    with pytest.raises(ValidationError):
        CallListParams.model_validate({"startedFrom": "2026-09-01T00:00:00"})


def test_a_window_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError):
        CallListParams.model_validate({"startedFrom": LATER, "startedTo": NOW})


def test_the_absence_filter_accepts_false_as_a_real_value() -> None:
    # `hasContact=false` is the work queue of this module, not an unset filter.
    params = CallListParams.model_validate({"hasContact": False})

    assert params.has_contact is False


@pytest.mark.parametrize(("sent", "expected"), [("true", True), ("false", False)])
def test_the_absence_filter_reads_the_string_a_query_string_carries(
    sent: str, expected: bool
) -> None:
    # A query parameter arrives as text; `?hasContact=false` has to mean what
    # it says rather than "a non-empty string, therefore true".
    assert CallListParams.model_validate({"hasContact": sent}).has_contact is expected


def test_an_unknown_query_parameter_is_ignored_rather_than_refused() -> None:
    # A query string picks up cache-busters on the way through a browser.
    params = CallListParams.model_validate({"utm_source": "mail", "page": 2})

    assert params.page == 2


def test_a_page_beyond_the_published_ceiling_is_refused() -> None:
    with pytest.raises(ValidationError):
        CallListParams.model_validate({"pageSize": 101})


@pytest.mark.parametrize("field", ["direction", "disposition"])
def test_a_filter_outside_the_closed_list_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        CallListParams.model_validate({field: "WHATEVER"})


def test_a_sort_column_outside_the_published_set_is_refused() -> None:
    # `sortBy` ends up in an ORDER BY clause; accepting whatever arrives would
    # make that clause caller-written SQL.
    with pytest.raises(ValidationError):
        CallListParams.model_validate({"sortBy": "fromNumber"})
