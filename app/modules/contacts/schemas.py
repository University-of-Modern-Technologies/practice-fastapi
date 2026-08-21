"""Wire contract of the contact endpoints.

Two rules live here rather than in the service, because they are statements
about the request and not about the stored record: a contact must be reachable
somehow (an address or a number), and a PATCH must actually ask for something.
"""

from __future__ import annotations

import uuid

from pydantic import Field, field_validator, model_validator

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SortOrder
from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.core.validation import EmailAddress
from app.modules.contacts.types import ContactSortField

MAX_NAME_LENGTH = 80
MAX_EMAIL_LENGTH = 320
MAX_PHONE_LENGTH = 32
MAX_COMPANY_LENGTH = 160
MAX_SEARCH_LENGTH = 160


def _trim(value: object) -> object:
    """Strips surrounding whitespace, leaving anything that is not text alone."""
    return value.strip() if isinstance(value, str) else value


def _fold_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


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


class ContactOut(CamelModel):
    """A contact as the API publishes it.

    ``deleted_at`` is deliberately absent: a soft-deleted record never leaves
    the service, so the flag would only ever be null on the wire.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    company: str | None
    notes: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ContactListParams(CamelModel):
    """Query accepted by ``GET /contacts``.

    Grouped into a model rather than spelled out as separate handler arguments;
    FastAPI reads a model as query parameters just as happily.

    The filter set is deliberately exactly the published one — an extra filter
    would make the two backends answer the same request differently.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    owner_id: uuid.UUID | None = None
    sort_by: ContactSortField = ContactSortField.CREATED_AT
    sort_order: SortOrder = "desc"

    @field_validator("search", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return _trim(value)

    @property
    def offset(self) -> int:
        """Row offset the page starts at."""
        return (self.page - 1) * self.page_size


class CreateContactRequest(CamelModel):
    """Body of ``POST /contacts``."""

    owner_id: uuid.UUID | None = None
    first_name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    last_name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    email: EmailAddress | None = Field(default=None, max_length=MAX_EMAIL_LENGTH)
    phone: str | None = Field(default=None, min_length=1, max_length=MAX_PHONE_LENGTH)
    company: str | None = Field(default=None, min_length=1, max_length=MAX_COMPANY_LENGTH)
    notes: str | None = Field(default=None, min_length=1)

    @field_validator("owner_id", mode="before")
    @classmethod
    def _require_owner(cls, value: object) -> object:
        return _reject_null(value)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        return _fold_email(_reject_null(value))

    @field_validator("first_name", "last_name", "phone", "company", "notes", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return _trim(_reject_null(value))

    @model_validator(mode="after")
    def _require_a_channel(self) -> CreateContactRequest:
        if not self.email and not self.phone:
            message = "Email or phone is required"
            raise ValueError(message)
        return self


class UpdateContactRequest(CamelModel):
    """Body of ``PATCH /contacts/{id}``.

    Every field is optional and null is a value in its own right — clearing an
    address is a legitimate edit. Which is why the service reads
    ``model_fields_set`` and not the values: an absent field means "leave as
    is", an explicit null means "erase".
    """

    owner_id: uuid.UUID | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    last_name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    email: EmailAddress | None = Field(default=None, max_length=MAX_EMAIL_LENGTH)
    phone: str | None = Field(default=None, min_length=1, max_length=MAX_PHONE_LENGTH)
    company: str | None = Field(default=None, min_length=1, max_length=MAX_COMPANY_LENGTH)
    notes: str | None = Field(default=None, min_length=1)

    # Owner and names back non-nullable columns, so an explicit null is a bad
    # request rather than an erasure.
    @field_validator("owner_id", mode="before")
    @classmethod
    def _require_owner(cls, value: object) -> object:
        return _reject_null(value)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _require_names(cls, value: object) -> object:
        return _trim(_reject_null(value))

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        return _fold_email(value)

    @field_validator("phone", "company", "notes", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return _trim(value)

    @model_validator(mode="after")
    def _require_one_field(self) -> UpdateContactRequest:
        if not self.model_fields_set:
            message = "At least one field is required"
            raise ValueError(message)
        return self
