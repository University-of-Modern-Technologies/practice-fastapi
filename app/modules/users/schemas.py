"""Wire contract of the user administration endpoints.

No schema here carries a password hash, in either direction: a field that is
never declared cannot be leaked by a future change to a serializer.
"""

from __future__ import annotations

import uuid

from pydantic import Field, field_validator, model_validator

from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.core.validation import EmailAddress

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_NAME_LENGTH = 120
MIN_ROLES = 1
MAX_ROLES = 20


def _normalise_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class UserRoleOut(CamelModel):
    """A role as it appears on a user record."""

    id: uuid.UUID
    name: str


class UserOut(CamelModel):
    """A user account."""

    id: uuid.UUID
    email: str
    name: str
    is_active: bool
    roles: list[UserRoleOut]
    created_at: UtcDatetime
    updated_at: UtcDatetime


class UserSessionOut(CamelModel):
    """One refresh grant, as shown in the account's device list."""

    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: UtcDatetime
    revoked_at: UtcDatetime | None
    ip_address: str | None
    user_agent: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CreateUserRequest(CamelModel):
    """Body of ``POST /users``."""

    email: EmailAddress
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    role_ids: list[uuid.UUID] = Field(min_length=MIN_ROLES, max_length=MAX_ROLES)

    @field_validator("email", mode="before")
    @classmethod
    def _fold_email(cls, value: object) -> object:
        return _normalise_email(value)


class UpdateUserRequest(CamelModel):
    """Body of ``PATCH /users/{id}``.

    Every field is optional, and an absent field means "leave as is" — which is
    why the service reads ``model_fields_set`` rather than the values.
    """

    email: EmailAddress | None = None
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )
    role_ids: list[uuid.UUID] | None = Field(
        default=None, min_length=MIN_ROLES, max_length=MAX_ROLES
    )

    @field_validator("email", mode="before")
    @classmethod
    def _fold_email(cls, value: object) -> object:
        return _normalise_email(value)

    @model_validator(mode="after")
    def _require_one_field(self) -> UpdateUserRequest:
        if not self.model_fields_set:
            message = "At least one field is required"
            raise ValueError(message)
        return self
