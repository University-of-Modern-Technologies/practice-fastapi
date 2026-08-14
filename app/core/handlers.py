"""Exception handlers.

Every failure leaves the application through exactly one shape:

``{"error": {"code": ..., "message": ..., "details": ...}, "requestId": ...}``

That includes the failures the framework raises on its own behalf. Left alone,
FastAPI answers a schema violation with HTTP 422 and a ``detail`` array, and
Starlette answers an unmatched route with a bare ``detail`` string — neither
matches the contract, so both are re-mapped here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.middleware.request_id import get_request_id

logger = get_logger(__name__)

# Location prefixes as FastAPI reports them, mapped onto the vocabulary used in
# the published contract.
_LOCATION_ALIASES = {"path": "params"}

NOT_FOUND_STATUS = 404

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMIT_EXCEEDED",
}


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Builds the single error shape the API is allowed to return."""
    error: dict[str, Any] = {"code": code, "message": message}
    # Omitted rather than sent as null: an absent key reads as "no further
    # information", which is exactly what it means.
    if details is not None:
        error["details"] = details

    return JSONResponse(
        status_code=status_code,
        content={"error": error, "requestId": get_request_id()},
    )


def flatten_validation_errors(errors: Sequence[Any]) -> dict[str, Any]:
    """Groups schema violations by the request part they came from.

    ``formErrors`` collects problems that belong to the request as a whole,
    ``fieldErrors`` groups the rest under ``body``, ``query`` or ``params``. The
    remaining path segments are folded into the message so nothing is lost.
    """
    form_errors: list[str] = []
    field_errors: dict[str, list[str]] = {}

    for error in errors:
        location = tuple(error.get("loc", ()))
        message = str(error.get("msg", "Invalid value"))

        if not location:
            form_errors.append(message)
            continue

        head = str(location[0])
        field = ".".join(str(segment) for segment in location[1:])
        field_errors.setdefault(_LOCATION_ALIASES.get(head, head), []).append(
            f"{field}: {message}" if field else message
        )

    return {"formErrors": form_errors, "fieldErrors": field_errors}


async def handle_app_error(_request: Request, exc: Exception) -> Response:
    error = exc if isinstance(exc, AppError) else AppError(str(exc), 500, "INTERNAL_SERVER_ERROR")
    logger.warning(error.message, code=error.code, status=error.status_code)
    return error_response(
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )


async def handle_validation_error(_request: Request, exc: Exception) -> Response:
    errors: Sequence[Any] = exc.errors() if isinstance(exc, RequestValidationError) else ()

    # A body that is not JSON at all is a different failure from a body that is
    # JSON but wrong, and the client can act on the distinction.
    if any(error.get("type") == "json_invalid" for error in errors):
        return error_response(
            status_code=400,
            code="INVALID_JSON",
            message="Malformed JSON request body",
        )

    return error_response(
        status_code=400,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=flatten_validation_errors(errors),
    )


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    status_code = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = getattr(exc, "detail", None)

    if status_code == NOT_FOUND_STATUS and detail in (None, "Not Found"):
        message = f"Route {request.method} {request.url.path} not found"
    else:
        message = str(detail) if detail else "Request failed"

    return error_response(
        status_code=status_code,
        code=_STATUS_CODES.get(status_code, f"HTTP_{status_code}"),
        message=message,
    )


def build_unhandled_handler(settings: Settings):  # type: ignore[no-untyped-def]
    """Creates the last-resort handler for anything that is not an `AppError`."""

    async def handle_unhandled(_request: Request, exc: Exception) -> Response:
        logger.error("Unhandled request error", exc_info=exc)
        return error_response(
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            # An unexpected exception message can carry internals — a table
            # name, a file path, part of a query — so it is only echoed where a
            # developer, not a user, is reading it.
            message="Internal server error" if settings.is_production else str(exc),
        )

    return handle_unhandled


def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, build_unhandled_handler(settings))
