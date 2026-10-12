"""Application service of the integrations module.

It owns one decision the client deliberately does not make: what may be
remembered. A quote is a pure read that repeats constantly, so it is memoised; a
shipment is a side effect and a tracking status that lags is worse than useless,
so neither is.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from app.cache.keys import cache_key
from app.core.errors import ConflictError, NotFoundError
from app.db.enums import PermissionScope
from app.modules.integrations.delivery.client import DeliveryClient
from app.modules.integrations.delivery.factory import DEFAULT_QUOTE_CACHE_TTL_SECONDS
from app.modules.integrations.schemas import CreateShipmentData, QuoteRequestData
from app.modules.integrations.types import (
    ORDER_NOT_FOUND,
    ORDER_NOT_SHIPPABLE,
    SHIPPABLE_ORDER_STATUSES,
    DeliveryHealthDto,
    DeliveryQuoteDto,
    FindOrderForShipment,
    NoopQuoteCache,
    QuoteCachePort,
    ShipmentAccess,
    ShipmentDto,
    ShipmentOrder,
)

__all__ = [
    "DELIVERY_NAMESPACE",
    "INTEGRATIONS_NAMESPACE",
    "IntegrationsService",
    "quote_cache_key",
]

INTEGRATIONS_NAMESPACE = "integrations"
DELIVERY_NAMESPACE = "delivery"

#: Length of the payload fingerprint inside the cache key. Half a SHA-256 is
#: far more than enough to keep two different quotes apart, and keeps the key
#: readable in a Redis dump.
CACHE_KEY_DIGEST_LENGTH = 32

#: The canonical spelling of an order id, and only that one. ``uuid.UUID``
#: alone would also take braces, a ``urn:uuid:`` prefix or no hyphens, which
#: the other backend refuses.
_ORDER_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


async def _find_no_order(
    order_id: uuid.UUID,  # noqa: ARG001
    actor_id: uuid.UUID,  # noqa: ARG001
    scope: PermissionScope,  # noqa: ARG001
) -> ShipmentOrder | None:
    """Used until the composition root supplies a real lookup: nothing is
    found, so every delivery is refused rather than shipped unchecked."""
    return None


def _stable_json(value: Any) -> str:
    """Serialises a payload so that key order cannot change the result.

    Two requests that differ only in the order their fields were written are the
    same request, and must not produce two cache entries.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def quote_cache_key(data: QuoteRequestData) -> str:
    """Cache key for one quote request."""
    payload = data.model_dump(mode="json", by_alias=True, exclude_none=True)
    digest = hashlib.sha256(_stable_json(payload).encode()).hexdigest()
    return cache_key(
        INTEGRATIONS_NAMESPACE,
        DELIVERY_NAMESPACE,
        "quote",
        digest[:CACHE_KEY_DIGEST_LENGTH],
    )


class IntegrationsService:
    """The module's use cases, one method each."""

    def __init__(
        self,
        client: DeliveryClient,
        cache: QuoteCachePort | None = None,
        quote_cache_ttl_seconds: int = DEFAULT_QUOTE_CACHE_TTL_SECONDS,
        find_order_for_shipment: FindOrderForShipment | None = None,
    ) -> None:
        self._client = client
        self._cache: QuoteCachePort = cache if cache is not None else NoopQuoteCache()
        self._quote_cache_ttl_seconds = quote_cache_ttl_seconds
        self._find_order: FindOrderForShipment = (
            find_order_for_shipment if find_order_for_shipment is not None else _find_no_order
        )

    async def request_quote(
        self, access: ShipmentAccess, data: QuoteRequestData
    ) -> DeliveryQuoteDto:
        """Prices a parcel, reusing a recent answer when there is one.

        ``remember`` fails open: an unreachable cache degrades to a live lookup
        rather than to an error. What is stored is the plain payload rather than
        the model, because a cache holds documents, not Python objects — and it
        is stored under the wire names, so an entry written here is readable by
        anything else that shares the cache.

        The order is checked first, on every call: a cached price is no licence
        to ship an order that has since been cancelled.
        """
        await self._assert_shippable_order(access, data.order_id)

        async def load() -> dict[str, Any]:
            quote = await self._client.request_quote(data)
            return quote.model_dump(mode="json", by_alias=True)

        cached = await self._cache.remember(
            quote_cache_key(data), self._quote_cache_ttl_seconds, load
        )
        return DeliveryQuoteDto.model_validate(cached)

    async def create_shipment(
        self, access: ShipmentAccess, data: CreateShipmentData
    ) -> ShipmentDto:
        """Books the parcel. Deliberately not cached: this is a side effect."""
        await self._assert_shippable_order(access, data.order_id)
        return await self._client.create_shipment(data)

    async def get_shipment(self, shipment_id: str) -> ShipmentDto:
        """Reads the tracking status. Deliberately not cached: it must be current."""
        return await self._client.get_shipment(shipment_id)

    def health(self) -> DeliveryHealthDto:
        return self._client.health()

    async def _assert_shippable_order(self, access: ShipmentAccess, order_id: str) -> None:
        """Refuses a delivery for an order that is not ready to leave.

        The order has to exist, be visible to the caller and be confirmed or
        paid. A missing order and one the caller may not see are the same
        answer, so the scope cannot be used to probe for identifiers. Nothing is
        asked of the carrier before this has passed.
        """
        if access.order_scope is None or not _ORDER_ID_PATTERN.fullmatch(order_id):
            raise NotFoundError("Order not found", ORDER_NOT_FOUND)
        order = await self._find_order(uuid.UUID(order_id), access.actor_id, access.order_scope)
        if order is None:
            raise NotFoundError("Order not found", ORDER_NOT_FOUND)
        if order.status in SHIPPABLE_ORDER_STATUSES:
            return
        raise ConflictError(
            "Order cannot be shipped in its current status",
            ORDER_NOT_SHIPPABLE,
            {
                "status": str(order.status),
                "allowed": [str(status) for status in SHIPPABLE_ORDER_STATUSES],
            },
        )
