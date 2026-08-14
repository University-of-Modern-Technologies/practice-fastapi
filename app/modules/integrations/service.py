"""Application service of the integrations module.

It owns one decision the client deliberately does not make: what may be
remembered. A quote is a pure read that repeats constantly, so it is memoised; a
shipment is a side effect and a tracking status that lags is worse than useless,
so neither is.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.cache.keys import cache_key
from app.modules.integrations.delivery.client import DeliveryClient
from app.modules.integrations.delivery.factory import DEFAULT_QUOTE_CACHE_TTL_SECONDS
from app.modules.integrations.schemas import CreateShipmentData, QuoteRequestData
from app.modules.integrations.types import (
    DeliveryHealthDto,
    DeliveryQuoteDto,
    NoopQuoteCache,
    QuoteCachePort,
    ShipmentDto,
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
    ) -> None:
        self._client = client
        self._cache: QuoteCachePort = cache if cache is not None else NoopQuoteCache()
        self._quote_cache_ttl_seconds = quote_cache_ttl_seconds

    async def request_quote(self, data: QuoteRequestData) -> DeliveryQuoteDto:
        """Prices a parcel, reusing a recent answer when there is one.

        ``remember`` fails open: an unreachable cache degrades to a live lookup
        rather than to an error. What is stored is the plain payload rather than
        the model, because a cache holds documents, not Python objects — and it
        is stored under the wire names, so an entry written here is readable by
        anything else that shares the cache.
        """

        async def load() -> dict[str, Any]:
            quote = await self._client.request_quote(data)
            return quote.model_dump(mode="json", by_alias=True)

        cached = await self._cache.remember(
            quote_cache_key(data), self._quote_cache_ttl_seconds, load
        )
        return DeliveryQuoteDto.model_validate(cached)

    async def create_shipment(self, data: CreateShipmentData) -> ShipmentDto:
        """Books the parcel. Deliberately not cached: this is a side effect."""
        return await self._client.create_shipment(data)

    async def get_shipment(self, shipment_id: str) -> ShipmentDto:
        """Reads the tracking status. Deliberately not cached: it must be current."""
        return await self._client.get_shipment(shipment_id)

    def health(self) -> DeliveryHealthDto:
        return self._client.health()
