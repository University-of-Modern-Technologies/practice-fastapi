"""What the service adds on top of the client: caching, and the refusal to cache."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.modules.integrations.delivery.factory import create_configured_delivery_client
from app.modules.integrations.schemas import CreateShipmentRequest, QuoteRequest
from app.modules.integrations.service import IntegrationsService, quote_cache_key
from app.modules.integrations.types import CircuitState, ShipmentStatus, TransportKind

QUOTE_REQUEST = QuoteRequest.model_validate(
    {
        "orderId": "ord_1",
        "origin": {"country": "PL", "city": "Warsaw", "postalCode": "00-001", "line1": "Street 1"},
        "destination": {
            "country": "DE",
            "city": "Berlin",
            "postalCode": "10115",
            "line1": "Street 2",
        },
        "parcel": {"weightGrams": 1_000, "lengthCm": 10, "widthCm": 10, "heightCm": 10},
    }
)


class MemoryCache:
    """Minimal in-memory cache; enough to prove the memoisation actually happens."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def remember[T](
        self,
        key: str,
        ttl_seconds: int,  # noqa: ARG002
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        if key in self.store:
            return self.store[key]  # type: ignore[no-any-return]
        value = await loader()
        self.store[key] = value
        return value


class CountingClient:
    """Counts what reached the client, and delegates the work to a real one."""

    def __init__(self) -> None:
        self._client = create_configured_delivery_client()
        self.quotes = 0
        self.shipments = 0

    async def request_quote(self, data: Any) -> Any:
        self.quotes += 1
        return await self._client.request_quote(data)

    async def create_shipment(self, data: Any) -> Any:
        self.shipments += 1
        return await self._client.create_shipment(data)

    async def get_shipment(self, shipment_id: str) -> Any:
        return await self._client.get_shipment(shipment_id)

    def health(self) -> Any:
        return self._client.health()


@pytest.fixture
def service() -> IntegrationsService:
    return IntegrationsService(create_configured_delivery_client())


async def test_it_runs_end_to_end_on_the_stub_transport_with_no_configuration(
    service: IntegrationsService,
) -> None:
    quote = await service.request_quote(QUOTE_REQUEST)
    assert quote.carrier == "Stub Express"
    assert quote.currency == "EUR"
    assert quote.estimated_days == 3

    shipment = await service.create_shipment(
        CreateShipmentRequest(
            quote_id=quote.quote_id,
            order_id=QUOTE_REQUEST.order_id,
            destination=QUOTE_REQUEST.destination,
            parcel=QUOTE_REQUEST.parcel,
        )
    )
    assert shipment.status is ShipmentStatus.CREATED
    assert shipment.order_id == "ord_1"

    fetched = await service.get_shipment(shipment.shipment_id)
    assert fetched.shipment_id == shipment.shipment_id

    health = service.health()
    assert health.transport is TransportKind.STUB
    assert health.circuit_state is CircuitState.CLOSED


async def test_the_stub_prices_the_same_request_the_same_way(
    service: IntegrationsService,
) -> None:
    first = await service.request_quote(QUOTE_REQUEST)
    second = await service.request_quote(QUOTE_REQUEST)

    assert second.quote_id == first.quote_id


async def test_the_amount_is_a_string_with_a_fixed_scale(service: IntegrationsService) -> None:
    quote = await service.request_quote(QUOTE_REQUEST)

    payload = quote.model_dump(mode="json", by_alias=True)
    assert payload["amount"] == "7.49"


async def test_a_repeated_quote_lookup_is_served_from_the_cache() -> None:
    client = CountingClient()
    service = IntegrationsService(client, MemoryCache())  # type: ignore[arg-type]

    first = await service.request_quote(QUOTE_REQUEST)
    second = await service.request_quote(QUOTE_REQUEST)

    assert client.quotes == 1
    assert second == first


async def test_the_cached_document_uses_the_wire_field_names() -> None:
    """The cache is shared, so an entry must be readable by whoever reads it next."""
    cache = MemoryCache()
    service = IntegrationsService(CountingClient(), cache)  # type: ignore[arg-type]

    await service.request_quote(QUOTE_REQUEST)

    document = cache.store[quote_cache_key(QUOTE_REQUEST)]
    assert "quoteId" in document
    assert "expiresAt" in document
    assert "quote_id" not in document
    assert "expires_at" not in document


def test_the_cache_key_ignores_field_order_but_not_field_values() -> None:
    reordered = QuoteRequest.model_validate(
        {
            "parcel": QUOTE_REQUEST.parcel.model_dump(by_alias=True),
            "destination": QUOTE_REQUEST.destination.model_dump(by_alias=True),
            "origin": QUOTE_REQUEST.origin.model_dump(by_alias=True),
            "orderId": QUOTE_REQUEST.order_id,
        }
    )

    assert quote_cache_key(reordered) == quote_cache_key(QUOTE_REQUEST)
    other = QUOTE_REQUEST.model_copy(update={"order_id": "ord_2"})
    assert quote_cache_key(other) != quote_cache_key(QUOTE_REQUEST)


def test_the_cache_key_lives_in_the_module_namespace() -> None:
    assert quote_cache_key(QUOTE_REQUEST).startswith("integrations:delivery:quote:")


async def test_shipment_creation_is_never_cached() -> None:
    client = CountingClient()
    service = IntegrationsService(client, MemoryCache())  # type: ignore[arg-type]

    data = CreateShipmentRequest(
        quote_id="qte_1",
        order_id="ord_1",
        destination=QUOTE_REQUEST.destination,
        parcel=QUOTE_REQUEST.parcel,
    )
    await service.create_shipment(data)
    await service.create_shipment(data)

    assert client.shipments == 2


async def test_a_heavy_parcel_is_quoted_as_freight(service: IntegrationsService) -> None:
    heavy = QUOTE_REQUEST.model_copy(
        update={"parcel": QUOTE_REQUEST.parcel.model_copy(update={"weight_grams": 25_000})}
    )

    quote = await service.request_quote(heavy)

    assert quote.service == "freight"
    assert quote.estimated_days == 5
