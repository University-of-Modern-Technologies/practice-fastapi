"""Wire contract of the call endpoints.

Two things are pinned here rather than left to a default.

Nothing a client sends describes the call itself. ``direction``, ``duration``,
the numbers, the moment it started — every one of those is the provider's
statement about traffic that already happened, so none of them appears in any
request body. What a client may state is what the call *means* to this
organization: who owns it, which contact and which deal it belongs to, and what
somebody wrote down about it.

And ``null`` is a value in its own right on every association. A call whose
contact is cleared is not a broken record — an operator who linked the wrong
customer has to be able to undo it, and the column is nullable precisely because
"nobody" is a legitimate answer.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SortOrder
from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.db.enums import CallDirection, CallDisposition
from app.modules.calls.types import (
    MAX_NOTES_LENGTH,
    MAX_NUMBER_LENGTH,
    MAX_SEARCH_LENGTH,
    CallSortField,
)

__all__ = [
    "E164_PATTERN",
    "CallListParams",
    "CallOut",
    "CallRecordingOut",
    "LinkCallRequest",
    "PhoneNumber",
    "SyncCallsOut",
    "UpdateCallRequest",
]

#: E.164 as the standard writes it: a leading plus, a country code that cannot
#: start with zero, and at most fifteen digits in total. Pinned here rather than
#: taken from a library, for the reason the email pattern is pinned in
#: ``app.core.validation``: two backends only stay interchangeable while both
#: draw the boundary in exactly the same place.
E164_PATTERN = r"^\+[1-9]\d{1,14}$"

#: A telephone number as this module accepts it from a provider.
PhoneNumber = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_NUMBER_LENGTH, pattern=E164_PATTERN
    ),
]

#: Optimistic locking counter as the client echoes it back.
Version = Annotated[int, Field(ge=1)]

Notes = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NOTES_LENGTH),
]


class CallOut(CamelModel):
    """A call as the API publishes it.

    ``deletedAt`` is deliberately absent: a soft-deleted record never leaves the
    service, so the flag would only ever be null on the wire.
    """

    id: uuid.UUID
    external_id: str
    direction: CallDirection
    disposition: CallDisposition
    from_number: str
    to_number: str
    started_at: UtcDatetime
    duration_seconds: int
    contact_id: uuid.UUID | None
    deal_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    recording_url: str | None
    notes: str | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class SyncCallsOut(CamelModel):
    """Outcome of one ``POST /calls/sync``.

    The three numbers are what makes a repeated sync legible: ``fetched`` is
    what the provider offered, ``created`` is what was new, and ``skipped`` is
    everything already on file. A second sync of an unchanged batch therefore
    reports the same ``fetched`` with ``created`` at zero, which is the visible
    form of the guarantee.
    """

    fetched: int = Field(ge=0)
    created: int = Field(ge=0)
    skipped: int = Field(ge=0)


class CallRecordingOut(CamelModel):
    """A playable link to the recording, and the moment it stops working.

    The link is short-lived on purpose: a recording is a conversation with a
    customer, and a URL that never expires is one that keeps working long after
    the person who was shown it stopped being allowed to hear it.
    """

    url: str
    expires_at: UtcDatetime


class UpdateCallRequest(CamelModel):
    """Body of ``PATCH /calls/{id}``.

    Exactly four fields are editable, and all four are associations or notes.
    An absent field means "leave as is" and an explicit ``null`` means "clear
    it" — which is why the service reads ``model_fields_set`` rather than the
    values.
    """

    version: Version
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    notes: Notes | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> Self:
        if self.model_fields_set <= {"version"}:
            message = "At least one field to update is required"
            raise ValueError(message)
        return self


class LinkCallRequest(CamelModel):
    """Body of ``POST /calls/{id}/link``.

    The narrow sibling of ``PATCH``: it attaches a call to the records it
    belongs to and does nothing else. Both associations are optional
    individually, but at least one of them has to name a record — a request
    that names neither is asking for no link at all, and answering it would
    burn a version and announce a ``call.linked`` that linked nothing.

    ``null`` is refused rather than read as "detach". This endpoint has one
    direction by design: detaching is an edit, so it goes through ``PATCH``,
    where ``null`` already means "clear it". One verb that both attaches and
    detaches would make ``call.linked`` in the audit trail ambiguous about
    which of the two it recorded.
    """

    version: Version
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None

    @field_validator("contact_id", "deal_id", mode="before")
    @classmethod
    def _reject_null(cls, value: object) -> object:
        # A default never reaches a validator, so this only ever sees a value
        # the client wrote down — which is what lets a field be omitted freely
        # while an explicit null stays an error.
        if value is None:
            message = "Value may not be null"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def _require_a_target(self) -> Self:
        if self.contact_id is None and self.deal_id is None:
            message = "A contact or a deal is required"
            raise ValueError(message)
        return self


class CallListParams(CamelModel):
    """Filters accepted when browsing the call log.

    Grouped into a model rather than spelled out as a dozen handler arguments;
    FastAPI reads a model as query parameters just as happily.

    Unlike a request body, an unknown parameter here is ignored rather than
    refused: a query string picks up cache-busters and tracking keys on the way
    through a browser, and none of them are the client asking for anything.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    direction: CallDirection | None = None
    disposition: CallDisposition | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    # A zone is required rather than assumed: "2026-09-01T00:00:00" means a
    # different instant in every office that sends it, and silently reading it
    # as UTC would answer a question the caller did not ask.
    started_from: AwareDatetime | None = None
    started_to: AwareDatetime | None = None
    #: Whether the call has been attached to a contact at all. The one filter
    #: that asks about absence, and the reason it exists: unattached calls are
    #: the work queue of this module.
    has_contact: bool | None = None
    sort_by: CallSortField = "startedAt"
    sort_order: SortOrder = "desc"

    @field_validator("search")
    @classmethod
    def _trim_search(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _require_ordered_window(self) -> Self:
        if (
            self.started_from is not None
            and self.started_to is not None
            and self.started_from > self.started_to
        ):
            message = "startedFrom must not be later than startedTo"
            raise ValueError(message)
        return self
