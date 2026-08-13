"""What a status change does to stock, and what it does when stock says no."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError
from app.db.enums import OrderStatus, PermissionScope
from app.db.models.order import Order, OrderItem
from app.events.types import DomainEvent
from app.modules.audit import AuditEvent, AuditService
from app.modules.orders.schemas import TransitionOrderRequest
from app.modules.orders.service import OrdersService
from app.modules.orders.stock import (
    OrdersStockPort,
    OrderStockChange,
    OrderStockInput,
    stock_effect_for_transition,
)
from app.modules.orders.types import OrderAccess

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ACTOR_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORDER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
WAREHOUSE_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
PRODUCT_ONE = uuid.UUID("44444444-4444-4444-4444-444444444444")
PRODUCT_TWO = uuid.UUID("55555555-5555-5555-5555-555555555555")
ITEM_ONE = uuid.UUID("66666666-6666-6666-6666-666666666666")
ITEM_TWO = uuid.UUID("77777777-7777-7777-7777-777777777777")

ACCESS = OrderAccess(actor_id=ACTOR_ID, scope=PermissionScope.OWN)


def _line(item_id: uuid.UUID, product_id: uuid.UUID, quantity: int) -> OrderItem:
    return OrderItem(
        id=item_id,
        order_id=ORDER_ID,
        product_id=product_id,
        sku=f"SKU-{product_id}",
        name=f"Product {product_id}",
        quantity=quantity,
        unit_price=Decimal("10.00"),
        line_total=Decimal(10 * quantity),
        # The lines share a timestamp on purpose: the id is what breaks the tie,
        # so the order the movements are requested in stays predictable.
        created_at=NOW,
        updated_at=NOW,
    )


def _order(status: OrderStatus, version: int = 1) -> Order:
    return Order(
        id=ORDER_ID,
        order_number="ORD-20260101-ABC123",
        owner_id=ACTOR_ID,
        contact_id=None,
        deal_id=None,
        status=status,
        currency="USD",
        subtotal=Decimal("50.00"),
        discount_total=Decimal("0.00"),
        tax_total=Decimal("0.00"),
        total=Decimal("50.00"),
        notes=None,
        version=version,
        placed_at=None,
        created_at=NOW,
        updated_at=NOW,
        items=[_line(ITEM_ONE, PRODUCT_ONE, 3), _line(ITEM_TWO, PRODUCT_TWO, 2)],
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


class FakeSession:
    """A scripted stand-in: selects are answered from a queue, updates counted."""

    def __init__(self, orders: list[Order]) -> None:
        self.orders = orders
        self.updates: list[Update] = []
        self.update_rowcount = 1

    async def execute(self, statement: Any) -> FakeResult:
        if isinstance(statement, Update):
            self.updates.append(statement)
            return FakeResult(rowcount=self.update_rowcount)
        current = self.orders.pop(0) if len(self.orders) > 1 else self.orders[0]
        return FakeResult([current])

    async def flush(self) -> None:
        return None


class RecordingAudit:
    def __init__(self, timeline: list[str]) -> None:
        self.events: list[AuditEvent] = []
        self._timeline = timeline

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        self._timeline.append(f"audit:{event.action}")


class RecordingPublisher:
    def __init__(self, timeline: list[str]) -> None:
        self.events: list[DomainEvent] = []
        self._timeline = timeline

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
        self._timeline.append("order-event")


class RecordingChange:
    def __init__(self, label: str, timeline: list[str]) -> None:
        self._label = label
        self._timeline = timeline

    def publish_committed(self) -> None:
        self._timeline.append(f"stock-event:{self._label}")


class RecordingOperations:
    """Records every request, and can be told to reject the reservation."""

    def __init__(self, timeline: list[str], reserve_error: AppError | None = None) -> None:
        self._timeline = timeline
        self._reserve_error = reserve_error
        self.reserved: list[OrderStockInput] = []
        self.released: list[OrderStockInput] = []
        self.issued: list[OrderStockInput] = []
        self.sessions: list[Any] = []

    async def reserve(
        self,
        session: AsyncSession,
        access: OrderAccess,  # noqa: ARG002
        data: OrderStockInput,
    ) -> OrderStockChange:
        if self._reserve_error is not None:
            raise self._reserve_error
        self.sessions.append(session)
        self.reserved.append(data)
        return RecordingChange("reserved", self._timeline)

    async def release(
        self,
        session: AsyncSession,
        access: OrderAccess,  # noqa: ARG002
        data: OrderStockInput,
    ) -> OrderStockChange:
        self.sessions.append(session)
        self.released.append(data)
        return RecordingChange("released", self._timeline)

    async def issue(
        self,
        session: AsyncSession,
        access: OrderAccess,  # noqa: ARG002
        data: OrderStockInput,
    ) -> OrderStockChange:
        self.sessions.append(session)
        self.issued.append(data)
        return RecordingChange("issued", self._timeline)


class Harness:
    """Everything one transition needs, wired to a scripted session."""

    def __init__(
        self,
        status: OrderStatus = OrderStatus.DRAFT,
        *,
        warehouse_id: uuid.UUID | None = WAREHOUSE_ID,
        reserve_error: AppError | None = None,
        with_stock: bool = True,
    ) -> None:
        self.timeline: list[str] = []
        self.warehouse_id = warehouse_id
        self.resolved = 0
        self.session = FakeSession([_order(status), _order(status, version=2)])
        self.audit = RecordingAudit(self.timeline)
        self.publisher = RecordingPublisher(self.timeline)
        self.operations = RecordingOperations(self.timeline, reserve_error)
        port = OrdersStockPort(
            operations=self.operations, resolve_warehouse_id=self._resolve_warehouse_id
        )
        self.service = OrdersService(
            cast(AsyncSession, self.session),
            cast(AuditService, self.audit),
            self.publisher,
            port if with_stock else None,
        )

    async def _resolve_warehouse_id(
        self,
        session: AsyncSession,  # noqa: ARG002
    ) -> uuid.UUID | None:
        self.resolved += 1
        return self.warehouse_id

    async def transition(self, to_status: OrderStatus) -> None:
        await self.service.transition(
            ACCESS, ORDER_ID, TransitionOrderRequest(version=1, status=to_status)
        )


class TestStockEffectTable:
    @pytest.mark.parametrize(
        ("from_status", "to_status", "effect"),
        [
            (OrderStatus.DRAFT, OrderStatus.CONFIRMED, "reserve"),
            (OrderStatus.CONFIRMED, OrderStatus.CANCELLED, "release"),
            (OrderStatus.PAID, OrderStatus.CANCELLED, "release"),
            (OrderStatus.PAID, OrderStatus.FULFILLED, "issue"),
            # Payment moves money, not goods; a cancelled draft never reserved.
            (OrderStatus.CONFIRMED, OrderStatus.PAID, None),
            (OrderStatus.DRAFT, OrderStatus.CANCELLED, None),
        ],
    )
    def test_derives_the_effect_from_the_pair_of_statuses(
        self, from_status: OrderStatus, to_status: OrderStatus, effect: str | None
    ) -> None:
        assert stock_effect_for_transition(from_status, to_status) == effect


class TestTransitionsThatMoveStock:
    async def test_reserves_every_line_when_a_draft_is_confirmed(self) -> None:
        harness = Harness()

        await harness.transition(OrderStatus.CONFIRMED)

        assert [(data.product_id, data.quantity) for data in harness.operations.reserved] == [
            (PRODUCT_ONE, 3),
            (PRODUCT_TWO, 2),
        ]
        assert all(data.warehouse_id == WAREHOUSE_ID for data in harness.operations.reserved)

    async def test_reserves_on_the_very_session_that_carries_the_status_change(self) -> None:
        harness = Harness()

        await harness.transition(OrderStatus.CONFIRMED)

        assert harness.operations.sessions == [harness.session, harness.session]
        assert len(harness.session.updates) == 1

    async def test_points_every_movement_back_at_the_order_that_caused_it(self) -> None:
        harness = Harness()

        await harness.transition(OrderStatus.CONFIRMED)

        for data in harness.operations.reserved:
            assert data.reference_type == "order"
            assert data.reference_id == ORDER_ID
            assert data.from_reservation is False

    @pytest.mark.parametrize("status", [OrderStatus.CONFIRMED, OrderStatus.PAID])
    def test_release_covers_both_stages_that_hold_a_reservation(self, status: OrderStatus) -> None:
        assert stock_effect_for_transition(status, OrderStatus.CANCELLED) == "release"

    async def test_releases_the_reservation_when_a_confirmed_order_is_cancelled(self) -> None:
        harness = Harness(OrderStatus.CONFIRMED)

        await harness.transition(OrderStatus.CANCELLED)

        assert len(harness.operations.released) == 2
        assert harness.operations.reserved == []
        assert harness.operations.issued == []

    async def test_issues_against_the_reservation_when_a_paid_order_is_fulfilled(self) -> None:
        harness = Harness(OrderStatus.PAID)

        await harness.transition(OrderStatus.FULFILLED)

        assert len(harness.operations.issued) == 2
        # Fulfilment consumes the reservation the confirmation created.
        assert all(data.from_reservation for data in harness.operations.issued)

    async def test_leaves_stock_alone_for_a_transition_that_only_moves_money(self) -> None:
        harness = Harness(OrderStatus.CONFIRMED)

        await harness.transition(OrderStatus.PAID)

        assert harness.resolved == 0
        assert harness.operations.reserved == []
        assert harness.operations.released == []

    async def test_leaves_stock_alone_when_a_draft_is_cancelled(self) -> None:
        harness = Harness()

        await harness.transition(OrderStatus.CANCELLED)

        assert harness.resolved == 0
        assert harness.operations.released == []

    async def test_publishes_the_stock_events_after_the_operation_succeeded(self) -> None:
        harness = Harness()

        await harness.transition(OrderStatus.CONFIRMED)

        assert harness.timeline == [
            "audit:order.status_transitioned",
            "stock-event:reserved",
            "stock-event:reserved",
            "order-event",
        ]


class TestTransitionsThatCannotMoveStock:
    async def test_a_rejected_reservation_takes_the_confirmation_down_with_it(self) -> None:
        harness = Harness(
            reserve_error=AppError("Not enough stock available", 409, "INSUFFICIENT_STOCK")
        )

        with pytest.raises(AppError) as error:
            await harness.transition(OrderStatus.CONFIRMED)

        assert error.value.code == "INSUFFICIENT_STOCK"
        # Nothing was announced, so no listener saw a confirmation that the
        # surrounding transaction is about to roll back.
        assert harness.publisher.events == []
        assert "stock-event:reserved" not in harness.timeline

    async def test_names_the_line_that_blocked_the_confirmation(self) -> None:
        harness = Harness(
            reserve_error=AppError("Not enough stock available", 409, "INSUFFICIENT_STOCK")
        )

        with pytest.raises(AppError) as error:
            await harness.transition(OrderStatus.CONFIRMED)

        assert error.value.details == {
            "orderId": str(ORDER_ID),
            "productId": str(PRODUCT_ONE),
            "quantity": 3,
        }

    async def test_refuses_the_transition_when_no_warehouse_is_configured(self) -> None:
        harness = Harness(warehouse_id=None)

        with pytest.raises(ConflictError) as error:
            await harness.transition(OrderStatus.CONFIRMED)

        assert error.value.code == "WAREHOUSE_NOT_CONFIGURED"
        assert harness.operations.reserved == []
        assert harness.publisher.events == []


class TestServiceWithoutAStockPort:
    async def test_confirms_an_order_and_touches_no_stock_at_all(self) -> None:
        harness = Harness(with_stock=False)

        await harness.transition(OrderStatus.CONFIRMED)

        assert harness.resolved == 0
        assert [event.event_type for event in harness.publisher.events] == [
            "order.status_transitioned"
        ]
