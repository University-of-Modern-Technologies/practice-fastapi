"""Domain vocabulary of the delivery integration.

These shapes are deliberately separate from the wire schemas in
``delivery/schemas.py``: the upstream service is free to change its payload, and
only the mapping layer has to follow. They double as the response models of the
module, which is the one place where the framework saves us a layer — a handler
returns the domain object and the serialiser is the schema itself.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.db.enums import OrderStatus, PermissionScope

__all__ = [
    "ORDER_NOT_FOUND",
    "ORDER_NOT_SHIPPABLE",
    "SHIPMENT_STATUSES",
    "SHIPPABLE_ORDER_STATUSES",
    "CircuitState",
    "DeliveryHealthDto",
    "DeliveryQuoteDto",
    "FindOrderForShipment",
    "NoopQuoteCache",
    "QuoteCachePort",
    "ShipmentAccess",
    "ShipmentDto",
    "ShipmentOrder",
    "ShipmentStatus",
    "TransportKind",
]

#: Machine codes of the order check that guards every delivery request.
ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
ORDER_NOT_SHIPPABLE = "ORDER_NOT_SHIPPABLE"

#: Order statuses a parcel may leave the warehouse in: confirmed (stock is
#: reserved) or already paid. A draft has nothing reserved yet, a cancelled
#: order has released its stock, and a fulfilled one has already been shipped.
SHIPPABLE_ORDER_STATUSES = (OrderStatus.CONFIRMED, OrderStatus.PAID)


@dataclass(frozen=True, slots=True)
class ShipmentAccess:
    """Who is asking for a delivery, and how much of the order book they see.

    The breadth is the caller's ``orders:read`` grant, not their integrations
    one: whether an order is visible is a question about orders. ``None`` means
    the caller sees no orders at all.
    """

    actor_id: uuid.UUID
    order_scope: PermissionScope | None


@dataclass(frozen=True, slots=True)
class ShipmentOrder:
    """The little the delivery integration needs to know about an order."""

    status: str


#: Reads the order a delivery is requested for.
#:
#: Contract for the implementation: return the order only if it exists, is not
#: soft-deleted and is visible at ``scope`` (``OWN`` — owned by ``actor_id``;
#: ``ALL`` — any owner); otherwise ``None``. Any status is returned: checking it
#: is the caller's business.
type FindOrderForShipment = Callable[
    [uuid.UUID, uuid.UUID, PermissionScope], Awaitable[ShipmentOrder | None]
]


class ShipmentStatus(enum.StrEnum):
    """Lifecycle of a parcel, as reported by the carrier."""

    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


#: The same values as a plain tuple, for schemas that validate a raw string.
SHIPMENT_STATUSES: tuple[str, ...] = tuple(status.value for status in ShipmentStatus)


class CircuitState(enum.StrEnum):
    """The three positions of the breaker in front of the upstream."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class TransportKind(enum.StrEnum):
    """Which transport is answering — the built-in stub or a real provider."""

    STUB = "stub"
    HTTP = "http"


class DeliveryQuoteDto(CamelModel):
    """A price for carrying one parcel, valid until ``expiresAt``."""

    quote_id: str
    carrier: str
    service: str
    #: The provider's own string, forwarded verbatim. It is somebody else's
    #: figure, not one of ours: re-scaling it here would report a price the
    #: carrier never quoted, so the wire form the upstream chose is preserved.
    amount: str
    currency: str
    estimated_days: int
    #: Forwarded verbatim for the same reason as ``amount``: the instant is the
    #: provider's statement about their own quote, and re-rendering it in our
    #: notation would report a moment they never wrote.
    expires_at: str


class ShipmentDto(CamelModel):
    """A parcel handed to the carrier, and where it currently is."""

    shipment_id: str
    order_id: str
    status: ShipmentStatus
    carrier: str
    tracking_number: str | None
    #: Verbatim, as on the quote above.
    created_at: str
    estimated_delivery_at: str | None


class DeliveryHealthDto(CamelModel):
    """Health payload for the integration.

    It intentionally carries no base URL, no credentials and no upstream error
    text — only the facts an operator needs in order to decide whether the
    dependency is healthy.
    """

    transport: TransportKind
    circuit_state: CircuitState
    consecutive_failures: int
    last_error_at: UtcDatetime | None
    opened_at: UtcDatetime | None


class QuoteCachePort(Protocol):
    """The one cache operation this module needs.

    Declared structurally so the module compiles, runs and is testable with no
    cache backend present at all.
    """

    async def remember[T](
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[T]],
    ) -> T: ...


class NoopQuoteCache:
    """Cache that stores nothing; the default when no backend is wired in."""

    async def remember[T](
        self,
        key: str,  # noqa: ARG002
        ttl_seconds: int,  # noqa: ARG002
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        return await loader()
