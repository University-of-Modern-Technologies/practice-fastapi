"""Wire contract of the helpdesk endpoints.

One thing is pinned here rather than left to a default: ``status`` appears in no
update body at all. The lifecycle is the server's to advance, so the field is
simply absent from the shape a ``PATCH`` accepts, and an attempt to smuggle it
in becomes a rejected request rather than a silent no-op.

``number`` is absent from every request body for the same kind of reason: the
human-readable number is allocated by the server, so a client has nothing to say
about it.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SortOrder
from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.db.enums import TicketChannel, TicketPriority, TicketStatus
from app.modules.helpdesk.types import (
    MAX_BODY_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_SEARCH_LENGTH,
    MAX_SUBJECT_LENGTH,
    TicketSortField,
)

#: Optimistic locking counter as the client echoes it back.
Version = Annotated[int, Field(ge=1)]
Subject = Annotated[str, Field(min_length=1, max_length=MAX_SUBJECT_LENGTH)]
Body = Annotated[str, Field(min_length=1, max_length=MAX_BODY_LENGTH)]
Note = Annotated[str, Field(min_length=1, max_length=MAX_NOTE_LENGTH)]


def _trim(value: object) -> object:
    """Strips surrounding whitespace, leaving anything that is not text alone."""
    return value.strip() if isinstance(value, str) else value


def _reject_null(value: object) -> object:
    """Refuses an explicitly sent ``null``.

    A default is never passed through a validator, so this only ever sees a
    value the client wrote down. That distinction is what lets a field be
    omitted freely while ``null`` stays an error on the fields whose column
    cannot hold one.
    """
    if value is None:
        message = "Value may not be null"
        raise ValueError(message)
    return value


class TicketOut(CamelModel):
    """A ticket as the API publishes it.

    ``deletedAt`` is deliberately absent: a soft-deleted record never leaves the
    service, so the flag would only ever be null on the wire.
    """

    id: uuid.UUID
    number: str
    subject: str
    body: str
    channel: TicketChannel
    status: TicketStatus
    priority: TicketPriority
    owner_id: uuid.UUID
    contact_id: uuid.UUID | None
    assignee_id: uuid.UUID | None
    version: int
    opened_at: UtcDatetime
    resolved_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CreateTicketRequest(CamelModel):
    """Body of ``POST /helpdesk/tickets``.

    ``status`` is absent from the shape: a ticket always opens at the beginning
    of the lifecycle, so there is nothing for the client to state, and letting
    it state one would be a way around the machine.
    """

    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    subject: Subject
    body: Body
    channel: TicketChannel
    priority: TicketPriority | None = None

    @field_validator("owner_id", "channel", "priority", mode="before")
    @classmethod
    def _require_value(cls, value: object) -> object:
        return _reject_null(value)

    @field_validator("subject", "body", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return _trim(_reject_null(value))


class UpdateTicketRequest(CamelModel):
    """Body of ``PATCH /helpdesk/tickets/{id}``.

    Every field but ``version`` is optional, and an absent field means "leave as
    is" — which is why the service reads ``model_fields_set`` rather than the
    values. ``contactId`` and ``assigneeId`` are the two that also accept an
    explicit ``null``, meaning "clear it": a ticket may legitimately belong to
    nobody in particular and to no contact on file.
    """

    version: Version
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    subject: Subject | None = None
    body: Body | None = None
    channel: TicketChannel | None = None
    priority: TicketPriority | None = None

    # Owner, channel and priority back non-nullable columns, so an explicit
    # null is a bad request rather than an erasure.
    @field_validator("owner_id", "channel", "priority", mode="before")
    @classmethod
    def _require_value(cls, value: object) -> object:
        return _reject_null(value)

    @field_validator("subject", "body", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return _trim(_reject_null(value))

    @model_validator(mode="after")
    def _require_one_field(self) -> Self:
        if self.model_fields_set <= {"version"}:
            message = "At least one field to update is required"
            raise ValueError(message)
        return self


class TransitionTicketRequest(CamelModel):
    """Body of ``POST /helpdesk/tickets/{id}/transitions``.

    The note is what the status log keeps: the machine records *that* a ticket
    moved, and this is the only place an operator can say why.
    """

    to_status: TicketStatus
    note: Note | None = None
    version: Version

    @field_validator("note", mode="before")
    @classmethod
    def _trim_note(cls, value: object) -> object:
        return _trim(value)


class TicketListParams(CamelModel):
    """Filters accepted when browsing tickets.

    Grouped into a model rather than spelled out as a dozen handler arguments;
    FastAPI reads a model as query parameters just as happily.

    Unlike a request body, an unknown parameter here is ignored rather than
    refused: a query string picks up cache-busters and tracking keys on the way
    through a browser, and none of them are the client asking for anything.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    status: TicketStatus | None = None
    channel: TicketChannel | None = None
    priority: TicketPriority | None = None
    contact_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    # A zone is required rather than assumed: "2026-08-01T00:00:00" means a
    # different instant in every office that sends it, and silently reading it
    # as UTC would answer a question the caller did not ask.
    opened_from: AwareDatetime | None = None
    opened_to: AwareDatetime | None = None
    sort_by: TicketSortField = "createdAt"
    sort_order: SortOrder = "desc"

    @field_validator("search")
    @classmethod
    def _trim_search(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _require_ordered_window(self) -> Self:
        if (
            self.opened_from is not None
            and self.opened_to is not None
            and self.opened_from > self.opened_to
        ):
            message = "openedFrom must not be later than openedTo"
            raise ValueError(message)
        return self
