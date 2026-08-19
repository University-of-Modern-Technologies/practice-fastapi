"""User administration: accounts, their roles and their sessions.

Mount with ``create_users_router()`` under ``/api/v1/users``.
"""

from __future__ import annotations

from app.modules.users.router import create_users_router, get_users_service
from app.modules.users.schemas import (
    CreateUserRequest,
    UpdateUserRequest,
    UserOut,
    UserRoleOut,
    UserSessionOut,
)
from app.modules.users.service import UsersService

__all__ = [
    "CreateUserRequest",
    "UpdateUserRequest",
    "UserOut",
    "UserRoleOut",
    "UserSessionOut",
    "UsersService",
    "create_users_router",
    "get_users_service",
]
