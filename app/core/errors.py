"""Typed application errors.

Every failure the API reports deliberately carries three things: the HTTP status
the client sees, a stable machine code the client may branch on, and an optional
details payload. Raising these instead of returning error flags keeps the happy
path of every service free of error plumbing.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every error that maps onto a deliberate HTTP response."""

    def __init__(
        self,
        message: str,
        status_code: int,
        code: str,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code}, code={self.code!r})"


class ValidationFailedError(AppError):
    """Request payload did not satisfy its schema."""

    def __init__(self, message: str = "Request validation failed", details: Any = None) -> None:
        super().__init__(message, 400, "VALIDATION_ERROR", details)


class UnauthorizedError(AppError):
    """No usable credentials were presented."""

    def __init__(self, message: str = "Unauthorized", code: str = "UNAUTHORIZED") -> None:
        super().__init__(message, 401, code)


class ForbiddenError(AppError):
    """Credentials are valid but do not grant the requested operation."""

    def __init__(self, message: str = "Forbidden", code: str = "FORBIDDEN") -> None:
        super().__init__(message, 403, code)


class NotFoundError(AppError):
    """The addressed resource does not exist, or is invisible to this caller."""

    def __init__(self, message: str = "Not found", code: str = "NOT_FOUND") -> None:
        super().__init__(message, 404, code)


class ConflictError(AppError):
    """The request contradicts the current state of the resource."""

    def __init__(self, message: str = "Conflict", code: str = "CONFLICT", details: Any = None):
        super().__init__(message, 409, code, details)


class VersionConflictError(ConflictError):
    """Optimistic locking rejected the write because the record moved on.

    Raised whenever an update carrying a ``version`` finds a different version
    stored. The client is expected to re-read and retry.

    The machine code is per resource — ``DEAL_CONCURRENT_MODIFICATION``,
    ``ORDER_CONCURRENT_MODIFICATION`` and so on — because a client that retries
    an order differently from a stock movement needs to tell them apart.
    """

    def __init__(
        self,
        message: str = "The record has been modified by someone else",
        code: str = "VERSION_CONFLICT",
    ) -> None:
        super().__init__(message, code)
