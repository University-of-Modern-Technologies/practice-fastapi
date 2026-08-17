"""Authentication: who is calling, and for how long.

Mount with ``create_auth_router()`` under ``/api/v1/auth``. Everything else in
this package exists for other modules to reuse — above all ``CurrentAuth``,
which is how a handler asks for a verified caller.
"""

from __future__ import annotations

from app.modules.auth.dependencies import CurrentAuth, get_auth, get_auth_service
from app.modules.auth.router import create_auth_router
from app.modules.auth.schemas import AuthenticatedUser, AuthPayload, LoginRequest, PermissionOut
from app.modules.auth.service import AuthService
from app.modules.auth.types import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    AuthConfig,
    AuthContext,
    AuthResult,
    auth_config_from_settings,
)

__all__ = [
    "REFRESH_COOKIE_NAME",
    "REFRESH_COOKIE_PATH",
    "AuthConfig",
    "AuthContext",
    "AuthPayload",
    "AuthResult",
    "AuthService",
    "AuthenticatedUser",
    "CurrentAuth",
    "LoginRequest",
    "PermissionOut",
    "auth_config_from_settings",
    "create_auth_router",
    "get_auth",
    "get_auth_service",
]
