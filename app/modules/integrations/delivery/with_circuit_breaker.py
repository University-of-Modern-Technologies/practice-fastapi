"""Wraps a delivery transport with a circuit breaker.

Every attempt made by the caller — including retries — passes through here, so
the breaker sees the true call volume rather than just the first attempt of
each request. Only transient outcomes count against it: network errors,
timeouts, 429 and 5xx. A 4xx response proves the upstream is alive and is
reported as a success, so a stream of bad requests from our side can never
trip it open.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.integrations.delivery.circuit_breaker import CircuitBreaker
from app.modules.integrations.delivery.transport import (
    DeliveryTransport,
    DeliveryTransportRequest,
    DeliveryTransportResponse,
)
from app.modules.integrations.types import TransportKind

__all__ = ["CircuitBreakerTransport", "CircuitOpenError"]

logger = get_logger("integrations.delivery")

_HTTP_OK_MIN = 200
_HTTP_OK_MAX = 300
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR_MIN = 500


def _is_transient_status(status: int) -> bool:
    return status == _HTTP_TOO_MANY_REQUESTS or status >= _HTTP_SERVER_ERROR_MIN


class CircuitOpenError(Exception):
    """Internal signal: the breaker refused the call before any network activity.

    Caught by the retry layer, which must fail fast instead of treating it
    like a transient response worth waiting out.
    """


class CircuitBreakerTransport:
    """A `DeliveryTransport` that consults a breaker before every send."""

    def __init__(self, transport: DeliveryTransport, breaker: CircuitBreaker) -> None:
        self._transport = transport
        self._breaker = breaker
        self.kind: TransportKind = transport.kind

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse:
        if not self._breaker.try_acquire():
            logger.warning("Delivery call short-circuited: breaker is open", path=request.path)
            raise CircuitOpenError

        try:
            response = await self._transport.send(request)
        except Exception:
            # A timeout or a socket error says nothing about our request and
            # everything about the dependency, so the breaker hears about it.
            self._breaker.on_failure()
            raise

        if _HTTP_OK_MIN <= response.status < _HTTP_OK_MAX:
            self._breaker.on_success()
        elif _is_transient_status(response.status):
            self._breaker.on_failure()
        else:
            # 4xx: the service is alive and is refusing *this* request. It
            # must not trip the breaker.
            self._breaker.on_success()

        return response
