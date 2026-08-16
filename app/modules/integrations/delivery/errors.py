"""Failure modes of the delivery integration.

Every way this integration can fail is translated into one of four codes.

The messages are written for the *caller of our API*, not for whoever is
debugging the upstream: they never contain the base URL, the API key, the raw
response body or the upstream error text. Those belong in the log line, which
stays on our side of the boundary.
"""

from __future__ import annotations

from app.core.errors import AppError

__all__ = [
    "DELIVERY_INVALID_RESPONSE",
    "DELIVERY_REJECTED",
    "DELIVERY_TIMEOUT",
    "DELIVERY_UNAVAILABLE",
    "delivery_invalid_response_error",
    "delivery_rejected_error",
    "delivery_timeout_error",
    "delivery_unavailable_error",
]

DELIVERY_TIMEOUT = "DELIVERY_TIMEOUT"
DELIVERY_UNAVAILABLE = "DELIVERY_UNAVAILABLE"
DELIVERY_REJECTED = "DELIVERY_REJECTED"
DELIVERY_INVALID_RESPONSE = "DELIVERY_INVALID_RESPONSE"

NOT_FOUND_STATUS = 404


def delivery_timeout_error() -> AppError:
    """The upstream did not answer within the per-request deadline."""
    return AppError("The delivery service did not respond in time", 504, DELIVERY_TIMEOUT)


def delivery_unavailable_error() -> AppError:
    """Network failure, 5xx, throttling, or a circuit that is currently open."""
    return AppError("The delivery service is temporarily unavailable", 503, DELIVERY_UNAVAILABLE)


def delivery_rejected_error(upstream_status: int) -> AppError:
    """The upstream understood the request and refused it.

    The service is healthy, so this never counts against the circuit breaker. A
    404 is passed through as 404 so that "no such shipment" stays
    distinguishable from "bad request".
    """
    if upstream_status == NOT_FOUND_STATUS:
        return AppError(
            "The delivery service has no record of this resource",
            NOT_FOUND_STATUS,
            DELIVERY_REJECTED,
        )
    return AppError("The delivery service rejected the request", 422, DELIVERY_REJECTED)


def delivery_invalid_response_error() -> AppError:
    """The upstream answered, but not with the payload its contract promises."""
    return AppError(
        "The delivery service returned an unexpected payload", 502, DELIVERY_INVALID_RESPONSE
    )
