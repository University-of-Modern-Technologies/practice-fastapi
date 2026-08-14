"""Order rules: derived totals, snapshots, optimistic locking, editability."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, VersionConflictError
from app.core.serializers import format_scaled_money
from app.db.enums import OrderStatus, PermissionScope
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.events.types import DomainEvent
from app.modules.audit import AuditEvent, AuditService
from app.modules.orders.schemas import (
    AddOrderItemRequest,
    CreateOrderRequest,
    OrderItemRequest,
    OrderListParams,
    TransitionOrderRequest,
    UpdateOrderItemRequest,
    UpdateOrderRequest,
)
from app.modules.orders.service import OrdersService, generate_order_number
from app.modules.orders.types import OrderAccess

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ACTOR_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
ORDER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PRODUCT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
ITEM_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")

OWN = OrderAccess(actor_id=ACTOR_ID, scope=PermissionScope.OWN)
ALL = OrderAccess(actor_id=ACTOR_ID, scope=PermissionScope.ALL)


def _product(
    *, unit_price: str = "19.99", is_active: bool = True, currency: str = "USD"
) -> Product:
    return Product(
        id=PRODUCT_ID,
        sku="SKU-1",
        name="Widget",
        unit_price=Decimal(unit_price),
        currency=currency,
        is_active=is_active,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _item(quantity: int = 2, unit_price: str = "19.99") -> OrderItem:
    return OrderItem(
        id=ITEM_ID,
        order_id=ORDER_ID,
        product_id=PRODUCT_ID,
        sku="SKU-1",
        name="Widget",
        quantity=quantity,
        unit_price=Decimal(unit_price),
        line_total=Decimal(unit_price) * quantity,
        created_at=NOW,
        updated_at=NOW,
    )


def _order(
    status: OrderStatus = OrderStatus.DRAFT,
    *,
    version: int = 1,
    items: list[OrderItem] | None = None,
    owner_id: uuid.UUID = ACTOR_ID,
) -> Order:
    lines = [_item()] if items is None else items
    subtotal = sum((line.line_total for line in lines), Decimal("0.00"))
    return Order(
        id=ORDER_ID,
        order_number="ORD-20260101-ABC123",
        owner_id=owner_id,
        contact_id=None,
        deal_id=None,
        status=status,
        currency="USD",
        subtotal=subtotal,
        discount_total=Decimal("0.00"),
        tax_total=Decimal("0.00"),
        total=subtotal,
        notes=None,
        version=version,
        placed_at=None,
        created_at=NOW,
        updated_at=NOW,
        items=lines,
    )


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def unique(self) -> FakeScalars:
        return self

    def all(self) -> list[Any]:
        return list(self._values)

    def one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class FakeResult:
    def __init__(self, values: list[Any] | None = None, rowcount: int = 0) -> None:
        self._values = values or []
        self.rowcount = rowcount

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)


class FakeNested:
    """Stands in for the savepoint the insert runs inside."""

    async def __aenter__(self) -> FakeNested:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakeSession:
    """A scripted stand-in: each select pops the next prepared answer."""

    def __init__(self, selects: list[list[Any]] | None = None) -> None:
        self.selects = selects or []
        self.scalars_queue: list[Any] = []
        self.updates: list[Update] = []
        self.update_rowcount = 1
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushes = 0

    async def execute(self, statement: Any) -> FakeResult:
        if isinstance(statement, Update):
            self.updates.append(statement)
            return FakeResult(rowcount=self.update_rowcount)
        return FakeResult(self.selects.pop(0) if self.selects else [])

    async def scalar(self, statement: Any) -> Any:  # noqa: ARG002
        return self.scalars_queue.pop(0) if self.scalars_queue else None

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        self.flushes += 1

    def begin_nested(self) -> FakeNested:
        return FakeNested()


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class ExplodingPublisher:
    def publish(self, event: DomainEvent) -> None:  # noqa: ARG002
        message = "the listener is broken"
        raise RuntimeError(message)


def _service(
    session: FakeSession,
    audit: RecordingAudit | None = None,
    publisher: Any = None,
) -> OrdersService:
    return OrdersService(
        cast(AsyncSession, session),
        cast(AuditService, audit or RecordingAudit()),
        publisher or RecordingPublisher(),
    )


class TestOrderNumber:
    def test_is_browsable_by_date_and_random_enough_to_survive_concurrency(self) -> None:
        number = generate_order_number()

        assert number.startswith("ORD-")
        prefix, day, suffix = number.split("-")
        assert prefix == "ORD"
        assert len(day) == 8
        assert len(suffix) == 6
        assert generate_order_number() != number


class TestCreate:
    async def test_derives_the_totals_from_the_lines(self) -> None:
        session = FakeSession([[_product()], [_order()]])
        service = _service(session)

        await service.create(
            OWN,
            CreateOrderRequest(
                items=[OrderItemRequest(product_id=PRODUCT_ID, quantity=3)],
                discount_total="5.00",
                tax_total="1.00",
            ),
        )

        order = cast(Order, session.added[0])
        assert format_scaled_money(order.subtotal) == "59.97"
        assert format_scaled_money(order.total) == "55.97"
        assert order.status == OrderStatus.DRAFT
        assert order.version is None or order.version == 1

    async def test_snapshots_the_catalogue_values_into_the_line(self) -> None:
        session = FakeSession([[_product()], [_order()]])
        service = _service(session)

        await service.create(
            OWN, CreateOrderRequest(items=[OrderItemRequest(product_id=PRODUCT_ID, quantity=2)])
        )

        line = cast(OrderItem, session.added[1])
        assert (line.sku, line.name) == ("SKU-1", "Widget")
        assert format_scaled_money(line.unit_price) == "19.99"
        assert format_scaled_money(line.line_total) == "39.98"

    async def test_records_the_creation_and_announces_it(self) -> None:
        session = FakeSession([[_product()], [_order()]])
        audit = RecordingAudit()
        publisher = RecordingPublisher()
        service = _service(session, audit, publisher)

        await service.create(
            OWN, CreateOrderRequest(items=[OrderItemRequest(product_id=PRODUCT_ID, quantity=1)])
        )

        assert [event.action for event in audit.events] == ["order.created"]
        assert audit.events[0].entity_type == "order"
        assert [event.event_type for event in publisher.events] == ["order.created"]

    async def test_refuses_a_product_that_is_not_in_the_catalogue(self) -> None:
        session = FakeSession([[]])
        service = _service(session)

        with pytest.raises(NotFoundError) as error:
            await service.create(
                OWN,
                CreateOrderRequest(items=[OrderItemRequest(product_id=PRODUCT_ID, quantity=1)]),
            )
        assert error.value.code == "PRODUCT_NOT_FOUND"

    async def test_refuses_a_product_that_is_no_longer_sold(self) -> None:
        session = FakeSession([[_product(is_active=False)]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.create(
                OWN,
                CreateOrderRequest(items=[OrderItemRequest(product_id=PRODUCT_ID, quantity=1)]),
            )
        assert error.value.code == "PRODUCT_INACTIVE"

    async def test_refuses_to_mix_currencies_on_one_order(self) -> None:
        session = FakeSession([[_product(currency="EUR")]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.create(
                OWN,
                CreateOrderRequest(items=[OrderItemRequest(product_id=PRODUCT_ID, quantity=1)]),
            )
        assert error.value.code == "ORDER_CURRENCY_MISMATCH"

    async def test_forbids_a_narrow_grant_from_placing_an_order_for_somebody_else(self) -> None:
        service = _service(FakeSession())

        with pytest.raises(ForbiddenError):
            await service.create(OWN, CreateOrderRequest(owner_id=OTHER_ID))

    async def test_a_wide_grant_may_place_an_order_on_behalf_of_another_owner(self) -> None:
        session = FakeSession([[_order()]])
        service = _service(session)

        await service.create(ALL, CreateOrderRequest(owner_id=OTHER_ID))

        assert cast(Order, session.added[0]).owner_id == OTHER_ID

    async def test_rejects_a_repeated_product_before_the_database_sees_it(self) -> None:
        with pytest.raises(ValueError, match="only once"):
            CreateOrderRequest(
                items=[
                    OrderItemRequest(product_id=PRODUCT_ID, quantity=1),
                    OrderItemRequest(product_id=PRODUCT_ID, quantity=2),
                ]
            )


class TestDuplicate:
    async def test_reprices_lines_from_the_current_catalogue(self) -> None:
        source = _order(items=[_item(unit_price="19.99")])
        session = FakeSession([[source], [_product(unit_price="25.00")], [_order()]])
        service = _service(session)

        await service.duplicate(OWN, ORDER_ID)

        line = cast(OrderItem, session.added[1])
        assert format_scaled_money(line.unit_price) == "25.00"
        assert format_scaled_money(line.line_total) == "50.00"

    async def test_copies_contact_owner_and_currency_but_starts_a_fresh_draft(self) -> None:
        source = _order(owner_id=OTHER_ID)
        source.contact_id = uuid.uuid4()
        session = FakeSession([[source], [_product()], [_order()]])
        session.scalars_queue = [source.contact_id]
        service = _service(session)

        await service.duplicate(ALL, ORDER_ID)

        order = cast(Order, session.added[0])
        assert order.owner_id == OTHER_ID
        assert order.contact_id == source.contact_id
        assert order.currency == source.currency
        assert order.status == OrderStatus.DRAFT
        assert order.version is None or order.version == 1
        assert order.order_number != source.order_number

    async def test_duplicates_a_source_order_in_any_status(self) -> None:
        source = _order(status=OrderStatus.CANCELLED)
        session = FakeSession([[source], [_product()], [_order()]])
        service = _service(session)

        await service.duplicate(OWN, ORDER_ID)

        order = cast(Order, session.added[0])
        assert order.status == OrderStatus.DRAFT, "duplicating is a new order, not a transition"

    async def test_refuses_a_product_that_has_gone_inactive_since(self) -> None:
        source = _order()
        session = FakeSession([[source], [_product(is_active=False)]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.duplicate(OWN, ORDER_ID)

        assert error.value.code == "PRODUCT_INACTIVE"
        assert session.added == []

    async def test_reports_the_same_404_as_a_plain_read_when_the_source_is_missing(self) -> None:
        service = _service(FakeSession([[]]))

        with pytest.raises(NotFoundError) as error:
            await service.duplicate(OWN, ORDER_ID)

        assert error.value.code == "ORDER_NOT_FOUND"

    async def test_records_and_announces_the_duplicate_like_a_plain_creation(self) -> None:
        source = _order()
        session = FakeSession([[source], [_product()], [_order()]])
        audit = RecordingAudit()
        publisher = RecordingPublisher()
        service = _service(session, audit, publisher)

        await service.duplicate(OWN, ORDER_ID)

        assert [event.action for event in audit.events] == ["order.created"]
        assert [event.event_type for event in publisher.events] == ["order.created"]


class TestUpdate:
    async def test_rejects_a_stale_version_without_writing(self) -> None:
        session = FakeSession([[_order(version=4)]])
        service = _service(session)

        with pytest.raises(VersionConflictError) as error:
            await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, notes="hi"))

        assert error.value.code == "ORDER_CONCURRENT_MODIFICATION"
        assert session.updates == []

    async def test_rejects_a_write_a_racing_request_already_won(self) -> None:
        session = FakeSession([[_order()], [_order(version=2)]])
        # The predicate matched no row: somebody else moved the order first.
        session.update_rowcount = 0
        service = _service(session)

        with pytest.raises(VersionConflictError):
            await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, notes="hi"))

    async def test_recomputes_the_totals_when_the_discount_changes(self) -> None:
        session = FakeSession([[_order()], [_order(version=2)]])
        service = _service(session)

        await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, discount_total="9.98"))

        values = session.updates[0].compile().params
        assert format_scaled_money(values["subtotal"]) == "39.98"
        assert format_scaled_money(values["total"]) == "30.00"

    async def test_refuses_to_touch_money_once_the_order_has_been_placed(self) -> None:
        session = FakeSession([[_order(OrderStatus.CONFIRMED)]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, tax_total="1.00"))

        assert error.value.code == "ORDER_NOT_EDITABLE"

    async def test_still_lets_a_placed_order_be_annotated(self) -> None:
        session = FakeSession([[_order(OrderStatus.CONFIRMED)], [_order(OrderStatus.CONFIRMED)]])
        service = _service(session)

        await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, notes="called client"))

        assert session.updates[0].compile().params["notes"] == "called client"

    async def test_refuses_to_repricce_an_order_by_changing_its_currency(self) -> None:
        session = FakeSession([[_order()]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, currency="eur"))

        assert error.value.code == "ORDER_CURRENCY_MISMATCH"

    async def test_requires_at_least_one_field_besides_the_version(self) -> None:
        with pytest.raises(ValueError, match="At least one field"):
            UpdateOrderRequest(version=1)

    async def test_a_broken_listener_cannot_fail_a_write_that_succeeded(self) -> None:
        session = FakeSession([[_order()], [_order(version=2)]])
        service = _service(session, publisher=ExplodingPublisher())

        result = await service.update(OWN, ORDER_ID, UpdateOrderRequest(version=1, notes="ok"))

        assert result.id == ORDER_ID


class TestItems:
    async def test_adds_a_line_and_rewrites_the_totals(self) -> None:
        other = uuid.UUID("77777777-7777-7777-7777-777777777777")
        product = _product()
        product.id = other
        session = FakeSession([[_order()], [product], [_order(version=2)]])
        service = _service(session)

        await service.add_item(
            OWN, ORDER_ID, AddOrderItemRequest(version=1, product_id=other, quantity=1)
        )

        added = cast(OrderItem, session.added[0])
        assert added.product_id == other
        values = session.updates[0].compile().params
        assert format_scaled_money(values["subtotal"]) == "59.97"

    async def test_refuses_a_product_that_is_already_on_the_order(self) -> None:
        session = FakeSession([[_order()]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.add_item(
                OWN, ORDER_ID, AddOrderItemRequest(version=1, product_id=PRODUCT_ID, quantity=1)
            )

        assert error.value.code == "ORDER_ITEM_DUPLICATE"

    async def test_refuses_to_change_the_lines_of_a_placed_order(self) -> None:
        session = FakeSession([[_order(OrderStatus.CONFIRMED)]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.add_item(
                OWN, ORDER_ID, AddOrderItemRequest(version=1, product_id=OTHER_ID, quantity=1)
            )

        assert error.value.code == "ORDER_NOT_EDITABLE"

    async def test_a_quantity_change_keeps_the_price_the_line_was_taken_at(self) -> None:
        order = _order()
        session = FakeSession([[order], [_order(version=2)]])
        service = _service(session)

        await service.update_item(
            OWN, ORDER_ID, ITEM_ID, UpdateOrderItemRequest(version=1, quantity=5)
        )

        line = order.items[0]
        assert format_scaled_money(line.unit_price) == "19.99"
        assert format_scaled_money(line.line_total) == "99.95"
        assert format_scaled_money(session.updates[0].compile().params["subtotal"]) == "99.95"

    async def test_removing_the_last_line_zeroes_the_order(self) -> None:
        order = _order()
        session = FakeSession([[order], [_order(version=2, items=[])]])
        service = _service(session)

        await service.remove_item(OWN, ORDER_ID, ITEM_ID, 1)

        assert session.deleted == [order.items[0]]
        assert format_scaled_money(session.updates[0].compile().params["total"]) == "0.00"

    async def test_reports_an_unknown_line_as_missing(self) -> None:
        session = FakeSession([[_order()]])
        service = _service(session)

        with pytest.raises(NotFoundError) as error:
            await service.remove_item(OWN, ORDER_ID, uuid.uuid4(), 1)

        assert error.value.code == "ORDER_ITEM_NOT_FOUND"


class TestLifecycleAndRemoval:
    async def test_confirmation_stamps_the_moment_the_order_was_placed(self) -> None:
        session = FakeSession([[_order()], [_order(OrderStatus.CONFIRMED, version=2)]])
        service = _service(session)

        await service.transition(
            OWN, ORDER_ID, TransitionOrderRequest(version=1, status=OrderStatus.CONFIRMED)
        )

        params = session.updates[0].compile().params
        assert params["status"] == OrderStatus.CONFIRMED
        assert params["placed_at"] is not None

    async def test_an_empty_draft_cannot_be_confirmed(self) -> None:
        session = FakeSession([[_order(items=[])]])
        service = _service(session)

        with pytest.raises(ConflictError) as error:
            await service.transition(
                OWN, ORDER_ID, TransitionOrderRequest(version=1, status=OrderStatus.CONFIRMED)
            )

        assert error.value.code == "ORDER_HAS_NO_ITEMS"

    async def test_deletion_is_soft_and_leaves_a_trail(self) -> None:
        session = FakeSession([[_order()]])
        audit = RecordingAudit()
        publisher = RecordingPublisher()
        service = _service(session, audit, publisher)

        await service.delete(OWN, ORDER_ID, 1)

        assert session.updates[0].compile().params["deleted_at"] is not None
        assert [event.action for event in audit.events] == ["order.deleted"]
        assert [event.event_type for event in publisher.events] == ["order.deleted"]


class TestReads:
    async def test_an_order_the_caller_may_not_see_is_reported_as_missing(self) -> None:
        service = _service(FakeSession([[]]))

        with pytest.raises(NotFoundError) as error:
            await service.get_by_id(OWN, ORDER_ID)

        assert error.value.code == "ORDER_NOT_FOUND"

    async def test_a_page_carries_the_orders_and_the_unpaged_total(self) -> None:
        session = FakeSession([[_order()]])
        session.scalars_queue = [7]
        service = _service(session)

        items, total = await service.list(OWN, OrderListParams())

        assert [item.id for item in items] == [ORDER_ID]
        assert total == 7

    async def test_the_lines_come_back_oldest_first(self) -> None:
        first = _item()
        second = _item()
        second.id = uuid.uuid4()
        second.created_at = NOW.replace(year=2027)
        session = FakeSession([[_order(items=[second, first])]])
        service = _service(session)

        order = await service.get_by_id(OWN, ORDER_ID)

        assert [item.id for item in order.items] == [first.id, second.id]
