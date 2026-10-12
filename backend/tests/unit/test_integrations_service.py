"""What the service adds on top of the client: caching, and the refusal to cache."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.core.errors import AppError
from app.core.settings import Settings
from app.db.enums import OrderStatus, PermissionScope
from app.modules.integrations.delivery.factory import create_configured_delivery_client
from app.modules.integrations.router import get_integrations_service
from app.modules.integrations.schemas import CreateShipmentRequest, QuoteRequest
from app.modules.integrations.service import IntegrationsService, quote_cache_key
from app.modules.integrations.types import (
    ORDER_NOT_FOUND,
    ORDER_NOT_SHIPPABLE,
    CircuitState,
    ShipmentAccess,
    ShipmentOrder,
    ShipmentStatus,
    TransportKind,
)

ORDER_ID = "7f1d2c3b-4a59-4e6f-8a7b-1c2d3e4f5a6b"
ACTOR_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
ACCESS = ShipmentAccess(actor_id=ACTOR_ID, order_scope=PermissionScope.ALL)

QUOTE_REQUEST = QuoteRequest.model_validate(
    {
        "orderId": ORDER_ID,
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


class OrderBook:
    """Holds one order, in whichever status the test needs, and records lookups."""

    def __init__(self, order: ShipmentOrder | None = None) -> None:
        self.order = order if order is not None else ShipmentOrder(status=OrderStatus.CONFIRMED)
        self.missing = False
        self.lookups: list[tuple[uuid.UUID, uuid.UUID, PermissionScope]] = []

    async def __call__(
        self, order_id: uuid.UUID, actor_id: uuid.UUID, scope: PermissionScope
    ) -> ShipmentOrder | None:
        self.lookups.append((order_id, actor_id, scope))
        return None if self.missing else self.order


def make_service(client: Any = None, cache: Any = None, book: OrderBook | None = None) -> Any:
    return IntegrationsService(
        client if client is not None else create_configured_delivery_client(),
        cache,
        find_order_for_shipment=book if book is not None else OrderBook(),
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
    return make_service()  # type: ignore[no-any-return]


async def test_it_runs_end_to_end_on_the_stub_transport_with_no_configuration(
    service: IntegrationsService,
) -> None:
    quote = await service.request_quote(ACCESS, QUOTE_REQUEST)
    assert quote.carrier == "Stub Express"
    assert quote.currency == "EUR"
    assert quote.estimated_days == 3

    shipment = await service.create_shipment(
        ACCESS,
        CreateShipmentRequest(
            quote_id=quote.quote_id,
            order_id=QUOTE_REQUEST.order_id,
            destination=QUOTE_REQUEST.destination,
            parcel=QUOTE_REQUEST.parcel,
        ),
    )
    assert shipment.status is ShipmentStatus.CREATED
    assert shipment.order_id == ORDER_ID

    fetched = await service.get_shipment(shipment.shipment_id)
    assert fetched.shipment_id == shipment.shipment_id

    health = service.health()
    assert health.transport is TransportKind.STUB
    assert health.circuit_state is CircuitState.CLOSED


async def test_the_stub_prices_the_same_request_the_same_way(
    service: IntegrationsService,
) -> None:
    first = await service.request_quote(ACCESS, QUOTE_REQUEST)
    second = await service.request_quote(ACCESS, QUOTE_REQUEST)

    assert second.quote_id == first.quote_id


async def test_the_amount_is_a_string_with_a_fixed_scale(service: IntegrationsService) -> None:
    quote = await service.request_quote(ACCESS, QUOTE_REQUEST)

    payload = quote.model_dump(mode="json", by_alias=True)
    assert payload["amount"] == "7.49"


async def test_a_repeated_quote_lookup_is_served_from_the_cache() -> None:
    client = CountingClient()
    service = make_service(client, MemoryCache())

    first = await service.request_quote(ACCESS, QUOTE_REQUEST)
    second = await service.request_quote(ACCESS, QUOTE_REQUEST)

    assert client.quotes == 1
    assert second == first


async def test_the_cached_document_uses_the_wire_field_names() -> None:
    """The cache is shared, so an entry must be readable by whoever reads it next."""
    cache = MemoryCache()
    service = make_service(CountingClient(), cache)

    await service.request_quote(ACCESS, QUOTE_REQUEST)

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
    service = make_service(client, MemoryCache())

    data = CreateShipmentRequest(
        quote_id="qte_1",
        order_id=ORDER_ID,
        destination=QUOTE_REQUEST.destination,
        parcel=QUOTE_REQUEST.parcel,
    )
    await service.create_shipment(ACCESS, data)
    await service.create_shipment(ACCESS, data)

    assert client.shipments == 2


async def test_a_heavy_parcel_is_quoted_as_freight(service: IntegrationsService) -> None:
    heavy = QUOTE_REQUEST.model_copy(
        update={"parcel": QUOTE_REQUEST.parcel.model_copy(update={"weight_grams": 25_000})}
    )

    quote = await service.request_quote(ACCESS, heavy)

    assert quote.service == "freight"
    assert quote.estimated_days == 5


async def test_the_quote_lifetime_comes_from_the_deployment_settings() -> None:
    lifetimes: list[int] = []

    class RecordingCache(MemoryCache):
        async def remember[T](
            self, key: str, ttl_seconds: int, loader: Callable[[], Awaitable[T]]
        ) -> T:
            lifetimes.append(ttl_seconds)
            return await super().remember(key, ttl_seconds, loader)

    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost:5432/crm",
        jwt_access_secret="a-secret-that-is-long-enough-here",
        jwt_refresh_secret="another-secret-long-enough-here!",
        redis_url="redis://localhost:6379",
        mongodb_url="mongodb://localhost:27017/events",
        delivery_quote_cache_ttl_seconds=7,
    )
    service = get_integrations_service(
        create_configured_delivery_client(), RecordingCache(), settings, OrderBook()
    )

    await service.request_quote(ACCESS, QUOTE_REQUEST)

    assert lifetimes == [7]


# --- the order a delivery is for ---------------------------------------------

SHIPMENT = CreateShipmentRequest(
    quote_id="qte_1",
    order_id=ORDER_ID,
    destination=QUOTE_REQUEST.destination,
    parcel=QUOTE_REQUEST.parcel,
)


@pytest.mark.parametrize("status", [OrderStatus.CONFIRMED, OrderStatus.PAID])
async def test_an_order_ready_to_leave_is_shipped(status: OrderStatus) -> None:
    book = OrderBook(ShipmentOrder(status=status))

    shipment = await make_service(book=book).create_shipment(ACCESS, SHIPMENT)

    assert shipment.order_id == ORDER_ID
    assert book.lookups == [(uuid.UUID(ORDER_ID), ACTOR_ID, PermissionScope.ALL)]


@pytest.mark.parametrize(
    "status", [OrderStatus.DRAFT, OrderStatus.CANCELLED, OrderStatus.FULFILLED]
)
async def test_an_order_not_ready_to_leave_is_refused_before_the_carrier_is_asked(
    status: OrderStatus,
) -> None:
    client = CountingClient()
    service = make_service(client, book=OrderBook(ShipmentOrder(status=status)))

    with pytest.raises(AppError) as quoted:
        await service.request_quote(ACCESS, QUOTE_REQUEST)
    with pytest.raises(AppError) as booked:
        await service.create_shipment(ACCESS, SHIPMENT)

    for error in (quoted.value, booked.value):
        assert error.status_code == 409
        assert error.code == ORDER_NOT_SHIPPABLE
        assert error.details == {"status": str(status), "allowed": ["CONFIRMED", "PAID"]}
    assert (client.quotes, client.shipments) == (0, 0)


async def test_a_missing_deleted_or_invisible_order_is_not_found() -> None:
    client = CountingClient()
    book = OrderBook()
    book.missing = True

    with pytest.raises(AppError) as error:
        await make_service(client, book=book).create_shipment(ACCESS, SHIPMENT)

    assert error.value.status_code == 404
    assert error.value.code == ORDER_NOT_FOUND
    assert client.shipments == 0


async def test_a_narrow_order_grant_narrows_the_lookup() -> None:
    book = OrderBook()
    own = ShipmentAccess(actor_id=ACTOR_ID, order_scope=PermissionScope.OWN)

    await make_service(book=book).request_quote(own, QUOTE_REQUEST)

    assert book.lookups == [(uuid.UUID(ORDER_ID), ACTOR_ID, PermissionScope.OWN)]


@pytest.mark.parametrize(
    ("order_scope", "order_id"),
    [
        (None, ORDER_ID),
        (PermissionScope.ALL, "ord_1"),
        (PermissionScope.ALL, "{" + ORDER_ID + "}"),
        (PermissionScope.ALL, ORDER_ID.replace("-", "")),
    ],
)
async def test_no_order_grant_or_no_order_id_is_not_found_without_a_lookup(
    order_scope: PermissionScope | None, order_id: str
) -> None:
    book = OrderBook()
    access = ShipmentAccess(actor_id=ACTOR_ID, order_scope=order_scope)

    with pytest.raises(AppError) as error:
        await make_service(book=book).create_shipment(
            access, SHIPMENT.model_copy(update={"order_id": order_id})
        )

    assert error.value.code == ORDER_NOT_FOUND
    assert book.lookups == []


async def test_the_order_is_checked_even_when_the_quote_is_cached() -> None:
    book = OrderBook()
    service = make_service(cache=MemoryCache(), book=book)

    await service.request_quote(ACCESS, QUOTE_REQUEST)
    book.order = ShipmentOrder(status=OrderStatus.CANCELLED)

    with pytest.raises(AppError) as error:
        await service.request_quote(ACCESS, QUOTE_REQUEST)

    assert error.value.code == ORDER_NOT_SHIPPABLE


async def test_every_delivery_is_refused_until_an_order_lookup_is_wired_in() -> None:
    service = IntegrationsService(create_configured_delivery_client())

    with pytest.raises(AppError) as error:
        await service.request_quote(ACCESS, QUOTE_REQUEST)

    assert error.value.status_code == 404
    assert error.value.code == ORDER_NOT_FOUND
