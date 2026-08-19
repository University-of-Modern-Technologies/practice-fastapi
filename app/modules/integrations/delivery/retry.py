"""Wraps a delivery transport with attempt counting, backoff and `Retry-After`.

Non-idempotent requests are sent exactly once, since replaying e.g. a shipment
creation after a timeout could hand the customer two parcels. An open circuit
(signalled by `CircuitOpenError`) fails fast: no wait, no further attempts,
regardless of how many attempts remain.
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
import random as random_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

from app.core.logging import get_logger
from app.modules.integrations.delivery.circuit_breaker import default_now_ms
from app.modules.integrations.delivery.errors import (
    delivery_rejected_error,
    delivery_timeout_error,
    delivery_unavailable_error,
)
from app.modules.integrations.delivery.transport import (
    DeliveryTransport,
    DeliveryTransportRequest,
    DeliveryTransportResponse,
    TransportTimeoutError,
)
from app.modules.integrations.delivery.with_circuit_breaker import CircuitOpenError
from app.modules.integrations.types import TransportKind

__all__ = [
    "DEFAULT_BASE_BACKOFF_MS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_BACKOFF_MS",
    "DEFAULT_MAX_RETRY_AFTER_MS",
    "DEFAULT_TIMEOUT_MS",
    "RetryOptions",
    "RetryingTransport",
    "parse_retry_after_ms",
]

logger = get_logger("integrations.delivery")

DEFAULT_TIMEOUT_MS = 5_000.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_BACKOFF_MS = 200.0
DEFAULT_MAX_BACKOFF_MS = 2_000.0
#: An upstream asking us to come back later than this is treated as "down".
DEFAULT_MAX_RETRY_AFTER_MS = 10_000.0

HTTP_OK_MIN = 200
HTTP_OK_MAX = 300
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR_MIN = 500


async def default_delay(milliseconds: float) -> None:
    await asyncio.sleep(milliseconds / 1000.0)


def _is_transient_status(status: int) -> bool:
    return status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR_MIN


def parse_retry_after_ms(value: str | None, now_ms: float) -> float | None:
    """Reads a ``Retry-After`` header.

    It is either a number of seconds or an HTTP date. Both forms are honoured;
    anything else is ignored rather than trusted.
    """
    if value is None:
        return None

    trimmed = value.strip()
    if not trimmed:
        return 0.0

    try:
        seconds = float(trimmed)
    except ValueError:
        pass
    else:
        if math.isfinite(seconds):
            return 0.0 if seconds <= 0 else float(round(seconds * 1_000))

    try:
        moment = parsedate_to_datetime(trimmed)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, moment.timestamp() * 1000.0 - now_ms)


@dataclass(frozen=True, slots=True)
class RetryOptions:
    """Everything the retry layer needs, with honest defaults.

    The clock, the randomness and the sleep are injectable for one reason: a
    retry policy that can only be observed in real time cannot be tested, and
    an untested retry policy is a way to take an upstream down twice as fast.
    """

    timeout_ms: float = DEFAULT_TIMEOUT_MS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_backoff_ms: float = DEFAULT_BASE_BACKOFF_MS
    max_backoff_ms: float = DEFAULT_MAX_BACKOFF_MS
    max_retry_after_ms: float = DEFAULT_MAX_RETRY_AFTER_MS
    now_ms: Callable[[], float] = default_now_ms
    random: Callable[[], float] = random_module.random
    delay: Callable[[float], Awaitable[None]] = default_delay


class RetryingTransport:
    """A `DeliveryTransport` that retries idempotent requests with backoff."""

    def __init__(self, transport: DeliveryTransport, options: RetryOptions) -> None:
        self._transport = transport
        self._options = options
        self.kind: TransportKind = transport.kind

    def _backoff_for(self, attempt: int) -> float:
        """Exponential backoff with full jitter.

        The nth retry waits a random slice of an exponentially growing window,
        so a fleet of instances that failed at the same moment does not come
        back in lockstep and knock the service over again.
        """
        window = min(
            self._options.max_backoff_ms, self._options.base_backoff_ms * 2.0 ** (attempt - 1)
        )
        return float(round(self._options.random() * window))

    async def _wait_before(
        self, attempt: int, response: DeliveryTransportResponse | None = None
    ) -> None:
        headers = {} if response is None else response.headers
        retry_after = parse_retry_after_ms(headers.get("retry-after"), self._options.now_ms())
        if retry_after is not None:
            # The upstream told us exactly when to come back; obey it instead
            # of guessing — unless it asks for longer than we are willing to
            # hold a request open, in which case the call fails fast.
            if retry_after > self._options.max_retry_after_ms:
                raise delivery_unavailable_error()
            await self._options.delay(retry_after)
            return
        await self._options.delay(self._backoff_for(attempt))

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse:
        attempts = 1 if request.idempotent is False else max(1, self._options.max_attempts)
        last_failure = delivery_unavailable_error()
        attempt_request = dataclasses.replace(request, timeout_ms=self._options.timeout_ms)

        for attempt in range(1, attempts + 1):
            try:
                response = await self._transport.send(attempt_request)
            except CircuitOpenError as error:
                raise delivery_unavailable_error() from error
            except Exception as error:
                # A timeout or a socket error says nothing about our request
                # and everything about the dependency.
                last_failure = (
                    delivery_timeout_error()
                    if isinstance(error, TransportTimeoutError)
                    else delivery_unavailable_error()
                )
                logger.warning(
                    "Delivery call failed", err=repr(error), attempt=attempt, path=request.path
                )
                if attempt == attempts:
                    raise last_failure from error
                await self._wait_before(attempt)
                continue

            if HTTP_OK_MIN <= response.status < HTTP_OK_MAX:
                return response

            if _is_transient_status(response.status):
                last_failure = delivery_unavailable_error()
                logger.warning(
                    "Delivery call returned a transient error",
                    attempt=attempt,
                    path=request.path,
                    status=response.status,
                )
                if attempt == attempts:
                    raise last_failure
                await self._wait_before(attempt, response)
                continue

            # 4xx: the service is alive and is refusing *this* request.
            # Retrying would only repeat the mistake.
            logger.warning(
                "Delivery service rejected the request", path=request.path, status=response.status
            )
            raise delivery_rejected_error(response.status)

        raise last_failure
