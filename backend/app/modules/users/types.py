"""Vocabulary of the user administration module."""

from __future__ import annotations

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = [
    "ADMIN_ROLE_NAME",
    "CANNOT_DISABLE_SELF",
    "DEFAULT_PAGE_SIZE",
    "EMAIL_ALREADY_EXISTS",
    "LAST_ACTIVE_ADMIN",
    "MAX_PAGE_SIZE",
    "SESSION_ENTITY_TYPE",
    "SESSION_NOT_FOUND",
    "SESSION_REVOKED",
    "USER_CREATED",
    "USER_DISABLED",
    "USER_ENTITY_TYPE",
    "USER_NOT_FOUND",
    "USER_OR_ROLE_NOT_FOUND",
    "USER_UPDATED",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side.
USER_NOT_FOUND = "USER_NOT_FOUND"
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
USER_OR_ROLE_NOT_FOUND = "USER_OR_ROLE_NOT_FOUND"
CANNOT_DISABLE_SELF = "CANNOT_DISABLE_SELF"
LAST_ACTIVE_ADMIN = "LAST_ACTIVE_ADMIN"

#: The role whose last active holder may not be disabled or stripped of it:
#: without one, nobody is left who can administer accounts.
ADMIN_ROLE_NAME = "admin"

#: Audit vocabulary of this module.
USER_ENTITY_TYPE = "user"
SESSION_ENTITY_TYPE = "session"
USER_CREATED = "user.created"
USER_UPDATED = "user.updated"
USER_DISABLED = "user.disabled"
SESSION_REVOKED = "session.revoked"
