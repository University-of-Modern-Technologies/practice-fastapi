"""Vocabulary of the user administration module."""

from __future__ import annotations

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "EMAIL_ALREADY_EXISTS",
    "MAX_PAGE_SIZE",
    "SESSION_NOT_FOUND",
    "USER_NOT_FOUND",
    "USER_OR_ROLE_NOT_FOUND",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side.
USER_NOT_FOUND = "USER_NOT_FOUND"
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
USER_OR_ROLE_NOT_FOUND = "USER_OR_ROLE_NOT_FOUND"
