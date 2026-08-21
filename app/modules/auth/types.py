"""Vocabulary of the authentication module.

``AuthContext`` is the one type every other module depends on, which is why it
lives here rather than inside the service: a domain module needs to know who is
calling without knowing how that was established.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Who is making the current request, and through which session."""

    user_id: uuid.UUID
    session_id: uuid.UUID


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
