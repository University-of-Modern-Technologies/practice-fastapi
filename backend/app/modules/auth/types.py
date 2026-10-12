"""Vocabulary of the authentication module.

``AuthContext`` is the one type every other module depends on, which is why it
lives here rather than inside the service: a domain module needs to know who is
calling without knowing how that was established.
"""

from __future__ import annotations

import contextlib
import ipaddress
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.core.settings import Settings
from app.modules.auth.schemas import AuthenticatedUser

#: Name of the cookie carrying the refresh token.
REFRESH_COOKIE_NAME = "refresh_token"

#: The cookie is scoped to the auth endpoints, so it is never attached to an
#: ordinary API call. The path has to match the mounted prefix exactly — a
#: narrower or wider path makes the browser withhold the cookie from refresh.
REFRESH_COOKIE_PATH = "/api/v1/auth"

ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60

#: Entropy of the refresh secret before base64url encoding.
REFRESH_SECRET_BYTES = 48

#: Separator between the session id and the secret inside a refresh token.
REFRESH_TOKEN_SEPARATOR = "."

#: Width of the ``user_agent`` column; a longer header is cut to fit.
MAX_USER_AGENT_LENGTH = 512


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Who is making the current request, and through which session."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    #: When the access token this identity was read from stops being valid.
    #: Not part of the identity itself, so two contexts of the same caller
    #: compare equal whatever token they came from.
    expires_at: datetime | None = field(default=None, compare=False)


@runtime_checkable
class SessionRevocationListener(Protocol):
    """Told about sessions that can no longer authenticate.

    Called once the change that ended them has committed. Whatever holds a
    connection open on the strength of such a session — the realtime gateway —
    closes it instead of waiting for the access token to run out.
    """

    def sessions_revoked(self, session_ids: Sequence[uuid.UUID]) -> None: ...

    def user_sessions_revoked(self, user_id: uuid.UUID) -> None:
        """Every session of this user ended at once."""
        ...


class NoopSessionRevocationListener:
    """Default for a service built without anything holding connections open."""

    def sessions_revoked(self, session_ids: Sequence[uuid.UUID]) -> None:
        """Intentionally empty: nothing is listening."""

    def user_sessions_revoked(self, user_id: uuid.UUID) -> None:
        """Intentionally empty: nothing is listening."""


def notify_sessions_revoked(
    listener: SessionRevocationListener,
    *,
    session_ids: Sequence[uuid.UUID] = (),
    user_id: uuid.UUID | None = None,
) -> None:
    """Delivers a notice without letting the listener fail the caller.

    The change it reports has already committed and must be answered as a
    success. The listener reports its own failures — the gateway logs every
    close it attempts — and the access token behind any socket left open runs
    out on its own.
    """
    with contextlib.suppress(Exception):
        if user_id is not None:
            listener.user_sessions_revoked(user_id)
        elif session_ids:
            listener.sessions_revoked(list(session_ids))


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Where a request came from, as recorded on the session it opens or renews."""

    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def of(cls, host: str | None, user_agent: str | None) -> ClientInfo:
        """Builds the record from raw connection data, dropping what cannot be stored."""
        return cls(
            ip_address=normalise_ip_address(host),
            user_agent=user_agent[:MAX_USER_AGENT_LENGTH] if user_agent else None,
        )


def normalise_ip_address(value: str | None) -> str | None:
    """A peer address in the form the ``inet`` column stores, or ``None``.

    Anything that is not an address — the placeholder host of an in-process
    transport, for one — is dropped rather than allowed to fail the write. An
    IPv4 peer seen through a dual-stack socket is unwrapped, so both servers
    record the same text for the same client.
    """
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Everything the auth service needs from configuration."""

    access_token_secret: str
    secure_cookies: bool
    access_token_ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS
    refresh_token_ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS
    refresh_cookie_name: str = REFRESH_COOKIE_NAME
    refresh_cookie_path: str = REFRESH_COOKIE_PATH


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Outcome of a login or a refresh: the account plus a fresh token pair."""

    user: AuthenticatedUser
    access_token: str
    refresh_token: str
    access_token_expires_in_seconds: int


def auth_config_from_settings(settings: Settings) -> AuthConfig:
    """Derives the auth configuration from the validated environment."""
    return AuthConfig(
        access_token_secret=settings.jwt_access_secret,
        # A cookie marked secure is dropped by the browser over plain HTTP,
        # which would break local development entirely.
        secure_cookies=settings.is_production,
    )


def refresh_cookie_kwargs(config: AuthConfig) -> dict[str, Any]:
    """Cookie attributes shared by the set and the clear call.

    They are produced in one place because a mismatch between the two — most
    easily in ``path`` — leaves the old cookie in the browser after logout.
    """
    return {
        "key": config.refresh_cookie_name,
        "httponly": True,
        "secure": config.secure_cookies,
        "samesite": "lax",
        "path": config.refresh_cookie_path,
    }
