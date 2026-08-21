"""The delivery client: everything between a domain call and the network.

Assembling the transport pipeline — circuit breaker, then retries — and
translating validated responses into domain DTOs live here. Retries, backoff
and the breaker itself live one layer down, in `retry.py` and
`with_circuit_breaker.py`, both of which wrap the same `DeliveryTransport`
port the client talks to.
"""

from __future__ import annotations

import random as random_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote as url_quote

from pydantic import BaseModel, ValidationError

from app.core.logging import get_logger
from app.modules.integrations.delivery.circuit_breaker import (
    DEFAULT_COOLDOWN_MS,
    DEFAULT_FAILURE_THRESHOLD,
    CircuitBreaker,
    default_now_ms,
)
from app.modules.integrations.delivery.errors import delivery_invalid_response_error
from app.modules.integrations.delivery.retry import (
    DEFAULT_BASE_BACKOFF_MS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_BACKOFF_MS,
    DEFAULT_MAX_RETRY_AFTER_MS,
    DEFAULT_TIMEOUT_MS,
    RetryingTransport,
    RetryOptions,
    default_delay,
    parse_retry_after_ms,
)
from app.modules.integrations.delivery.schemas import (
    UpstreamQuote,
    UpstreamShipment,
    to_delivery_quote_dto,
    to_shipment_dto,
)
from app.modules.integrations.delivery.transport import (
    DeliveryTransport,
    DeliveryTransportRequest,
)
from app.modules.integrations.delivery.with_circuit_breaker import CircuitBreakerTransport
from app.modules.integrations.schemas import CreateShipmentData, QuoteRequestData
from app.modules.integrations.types import (
    DeliveryHealthDto,
    DeliveryQuoteDto,
    ShipmentDto,
)

__all__ = [
    "DEFAULT_BASE_BACKOFF_MS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_BACKOFF_MS",
    "DEFAULT_MAX_RETRY_AFTER_MS",
    "DEFAULT_TIMEOUT_MS",
    "DeliveryClient",
    "DeliveryClientOptions",
    "parse_retry_after_ms",
]

logger = get_logger("integrations.delivery")

QUOTES_PATH = "/v1/quotes"
SHIPMENTS_PATH = "/v1/shipments"

HTTP_OK_MIN = 200
HTTP_OK_MAX = 300


@dataclass(frozen=True, slots=True)
class DeliveryClientOptions:
    """Everything the client needs, with honest defaults.

    The clock, the randomness and the sleep are injectable for one reason: a
    retry policy that can only be observed in real time cannot be tested, and
    an untested retry policy is a way to take an upstream down twice as fast.
    """

    transport: DeliveryTransport
    #: Per-attempt deadline.
    timeout_ms: float = DEFAULT_TIMEOUT_MS
    #: Total attempts for an idempotent call, including the first one.
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_backoff_ms: float = DEFAULT_BASE_BACKOFF_MS
    max_backoff_ms: float = DEFAULT_MAX_BACKOFF_MS
    max_retry_after_ms: float = DEFAULT_MAX_RETRY_AFTER_MS
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    cooldown_ms: float = DEFAULT_COOLDOWN_MS
    now_ms: Callable[[], float] = default_now_ms
    random: Callable[[], float] = random_module.random
    delay: Callable[[float], Awaitable[None]] = default_delay


@dataclass(frozen=True, slots=True)
class CallSpec[TModel: BaseModel]:
    """One logical upstream operation, independent of how often it is attempted."""

    method: Literal["GET", "POST"]
    path: str
    #: Only idempotent calls are retried. Replaying a shipment creation after a
    #: timeout could hand the customer two parcels, so that one is sent once and
    #: its failure is reported honestly.
    idempotent: bool
    schema: type[TModel]
    body: Any = field(default=None)


class DeliveryClient:
    """Calls the carrier, and keeps its bad days from becoming ours."""

    def __init__(self, options: DeliveryClientOptions) -> None:
        self._options = options
        self._transport = options.transport
        self._breaker = CircuitBreaker(
            failure_threshold=options.failure_threshold,
            cooldown_ms=options.cooldown_ms,
            now_ms=options.now_ms,
        )
        # Order matters: the breaker must see every attempt, not just the
        # first, so it sits inside the retry layer rather than around it.
        self._wire = RetryingTransport(
            CircuitBreakerTransport(options.transport, self._breaker),
            RetryOptions(
                timeout_ms=options.timeout_ms,
                max_attempts=options.max_attempts,
                base_backoff_ms=options.base_backoff_ms,
                max_backoff_ms=options.max_backoff_ms,
                max_retry_after_ms=options.max_retry_after_ms,
                now_ms=options.now_ms,
                random=options.random,
                delay=options.delay,
            ),
        )

    def _parse[TModel: BaseModel](self, schema: type[TModel], body: Any) -> TModel:
        try:
            return schema.model_validate(body)
        except ValidationError as error:
            # The details stay in our logs: the client only learns that the
            # upstream contract was violated, never what the upstream sent.
            logger.error(
                "Delivery service returned a payload that failed validation",
                issues=error.errors(include_url=False),
            )
            raise delivery_invalid_response_error() from error

    async def _call[TModel: BaseModel](self, spec: CallSpec[TModel]) -> TModel:
        response = await self._wire.send(
            DeliveryTransportRequest(
                method=spec.method,
                path=spec.path,
                idempotent=spec.idempotent,
                body=spec.body,
            )
        )
        return self._parse(spec.schema, response.body)

    async def request_quote(self, data: QuoteRequestData) -> DeliveryQuoteDto:
        """Prices one parcel.

        A quote is a pure read: computing it twice costs nothing, so it retries.
        """
        body: dict[str, Any] = {
            "order_id": data.order_id,
            "origin": data.origin.model_dump(by_alias=True),
            "destination": data.destination.model_dump(by_alias=True),
            "parcel": data.parcel.model_dump(by_alias=True),
        }
        if data.declared_value is not None:
            body["declared_value"] = data.declared_value

        quote = await self._call(
            CallSpec(
                method="POST",
                path=QUOTES_PATH,
                idempotent=True,
                schema=UpstreamQuote,
                body=body,
            )
        )
        return to_delivery_quote_dto(quote)

    async def create_shipment(self, data: CreateShipmentData) -> ShipmentDto:
        """Books a parcel with the carrier. Sent once, never replayed."""
        body: dict[str, Any] = {
            "quote_id": data.quote_id,
            "order_id": data.order_id,
            "destination": data.destination.model_dump(by_alias=True),
            "parcel": data.parcel.model_dump(by_alias=True),
        }
        if data.reference is not None:
            body["reference"] = data.reference

        shipment = await self._call(
            CallSpec(
                method="POST",
                path=SHIPMENTS_PATH,
                idempotent=False,
                schema=UpstreamShipment,
                body=body,
            )
        )
        return to_shipment_dto(shipment)

    async def get_shipment(self, shipment_id: str) -> ShipmentDto:
        shipment = await self._call(
            CallSpec(
                method="GET",
                path=f"{SHIPMENTS_PATH}/{url_quote(shipment_id, safe='')}",
                idempotent=True,
                schema=UpstreamShipment,
            )
        )
        return to_shipment_dto(shipment)

    def health(self) -> DeliveryHealthDto:
        snapshot = self._breaker.snapshot()
        return DeliveryHealthDto(
            transport=self._transport.kind,
            circuit_state=snapshot.state,
            consecutive_failures=snapshot.consecutive_failures,
            last_error_at=_instant_or_none(snapshot.last_error_at_ms),
            opened_at=_instant_or_none(snapshot.opened_at_ms),
        )


def _instant_or_none(milliseconds: float | None) -> datetime | None:
    return None if milliseconds is None else datetime.fromtimestamp(milliseconds / 1000.0, UTC)
