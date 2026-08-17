"""Wire contract of the authentication endpoints."""

from __future__ import annotations

import uuid

from pydantic import Field, field_validator

from app.core.responses import CamelModel
from app.core.validation import EmailAddress
from app.db.enums import PermissionScope

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class LoginRequest(CamelModel):
    """Credentials presented at ``POST /auth/login``."""

    email: EmailAddress
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        # Addresses are stored lowercased, so a login typed with capitals has to
        # be folded before it reaches the lookup — otherwise the same account
        # exists twice as far as the client can tell.
        return value.strip().lower() if isinstance(value, str) else value


class PermissionOut(CamelModel):
    """One capability, at the breadth it was granted."""

    resource: str
    action: str
    scope: PermissionScope


class AuthenticatedUser(CamelModel):
    """The signed-in account as the client sees it.

    The permission list is flattened across every role the user holds because
    the client builds its navigation and its per-record affordances from this
    array alone.
    """

    id: uuid.UUID
    email: str
    name: str
    roles: list[str]
    permissions: list[PermissionOut]


class AuthPayload(CamelModel):
    """Body of a successful login or refresh."""

    user: AuthenticatedUser
    access_token: str
    access_token_expires_in_seconds: int
