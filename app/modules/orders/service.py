"""Order rules: lines, money, the lifecycle and the stock it moves.

Three invariants shape this module.

The totals are never taken from the request: they are recomputed from the lines
on every write, so an order can never claim a price its lines do not add up to.

A write carries the version the client last read. The optimistic-locking
predicate names that version *and* the status, so a racing writer who already
moved the order loses this write instead of overwriting it.

The stock movements of a transition run on the very session that carries the
status change. A reservation that cannot be met therefore takes the confirmation
down with it, and no separate commit can leave the two disagreeing.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.errors import VersionConflictError as StaleVersionError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.db.enums import OrderStatus, PermissionScope
from app.db.models.contact import Contact
from app.db.models.deal import Deal
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.orders.money import (
    ZERO_MONEY,
    OrderTotals,
    calculate_line_total,
    calculate_order_totals,
    normalize_money,
)
from app.modules.orders.schemas import (
    AddOrderItemRequest,
    CreateOrderRequest,
    OrderItemOut,
    OrderItemRequest,
    OrderListParams,
    OrderOut,
    TransitionOrderRequest,
    UpdateOrderItemRequest,
    UpdateOrderRequest,
)
from app.modules.orders.stock import (
    ORDER_STOCK_REFERENCE_TYPE,
    OrdersStockPort,
    OrderStockEffect,
    OrderStockInput,
    stock_effect_for_transition,
)
from app.modules.orders.transition import (
    assert_order_editable,
    assert_order_has_items,
    assert_order_status_transition,
)
from app.modules.orders.types import (
    CONTACT_NOT_FOUND,
    DEAL_NOT_FOUND,
    ORDER_CONCURRENT_MODIFICATION,
    ORDER_CURRENCY_MISMATCH,
    ORDER_ENTITY_TYPE,
    ORDER_ITEM_DUPLICATE,
    ORDER_ITEM_NOT_FOUND,
    ORDER_NOT_FOUND,
    ORDER_NUMBER_UNAVAILABLE,
    PRODUCT_INACTIVE,
    PRODUCT_NOT_FOUND,
    WAREHOUSE_NOT_CONFIGURED,
    OrderAccess,
)

DEFAULT_CURRENCY = "USD"

#: Bounded so a pathological collision streak fails fast instead of looping.
ORDER_NUMBER_ATTEMPTS = 5

_ITEMS = selectinload(Order.items)

_SORT_COLUMNS: Mapping[str, InstrumentedAttribute[Any]] = {
    "createdAt": Order.created_at,
    "updatedAt": Order.updated_at,
    "orderNumber": Order.order_number,
    "total": Order.total,
    "placedAt": Order.placed_at,
    "status": Order.status,
}


@dataclass(frozen=True, slots=True)
class _OrderLine:
    """A resolved order line, priced from the catalogue as it stands now."""

    product_id: uuid.UUID
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


# The service defines a method called ``list``, which shadows the builtin inside
# the class body. These aliases are resolved out here, where it does not.
type Criteria = list[Any]
type Lines = list[_OrderLine]
type Publishers = list[Callable[[], None]]
type OrderPage = tuple[list[OrderOut], int]


def generate_order_number() -> str:
    """Human-readable and collision-resistant.

    The date prefix keeps the sequence browsable while the random suffix keeps
    concurrent writers apart; a collision is still possible and is retried.
    """
    day = datetime.now(tz=UTC).strftime("%Y%m%d")
    suffix = "".join(secrets.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(6))
    return f"ORD-{day}-{suffix}"


def to_item_out(item: OrderItem) -> OrderItemOut:
    return OrderItemOut(
        id=item.id,
        order_id=item.order_id,
        product_id=item.product_id,
        sku=item.sku,
        name=item.name,
        quantity=item.quantity,
        unit_price=item.unit_price,
        line_total=item.line_total,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def to_order_out(order: Order) -> OrderOut:
    """Renders an order and its lines, oldest line first."""
    items = sorted(order.items, key=lambda item: (item.created_at, str(item.id)))
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        owner_id=order.owner_id,
        contact_id=order.contact_id,
        deal_id=order.deal_id,
        status=order.status,
        currency=order.currency,
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        tax_total=order.tax_total,
        total=order.total,
        notes=order.notes,
        version=order.version,
        placed_at=order.placed_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[to_item_out(item) for item in items],
    )


def _dump(dto: OrderOut) -> dict[str, Any]:
    """The JSON shape of an order, for the audit trail and the event log."""
    return dto.model_dump(mode="json", by_alias=True)


def _is_order_number_conflict(error: IntegrityError) -> bool:
    """A collision on the generated number is expected under concurrency.

    Any other uniqueness violation belongs to the caller's payload and is
    reported rather than retried.
    """
    return "order_number" in str(error.orig).lower()


def _owner_criteria(access: OrderAccess) -> Criteria:
    """A caller holding ``OWN`` only ever addresses their own orders."""
    if access.scope == PermissionScope.OWN:
        return [Order.owner_id == access.actor_id]
    return []


class _OrderListPage(PagedQuery[Order, OrderListParams, OrderOut]):
    """One page of orders the caller is allowed to see.

    Every row carries its lines, loaded through the same eager-load option the
    single-order read uses, so a page never triggers one query per row to
    render its items.
    """

    def __init__(self, session: AsyncSession, access: OrderAccess) -> None:
        super().__init__(session)
        self._access = access

    def _model(self) -> type[Order]:
        return Order

    def _build_filters(self, params: OrderListParams) -> list[ColumnElement[bool]]:
        owner_id = params.owner_id if self._access.scope != PermissionScope.OWN else None
        return (
            FilterBuilder([Order.deleted_at.is_(None), *_owner_criteria(self._access)])
            .equals(Order.owner_id, owner_id)
            .equals(Order.contact_id, params.contact_id)
            .equals(Order.deal_id, params.deal_id)
            .equals(Order.status, params.status)
            .search(params.search, [Order.order_number])
            .range(
                Order.total,
                Decimal(params.min_total) if params.min_total is not None else None,
                Decimal(params.max_total) if params.max_total is not None else None,
            )
            .build()
        )

    def _order_by(self, params: OrderListParams) -> tuple[ColumnElement[Any], ...]:
        column = _SORT_COLUMNS[params.sort_by]
        ordering = column.asc() if params.sort_order == "asc" else column.desc()
        # Tie-broken by id: two orders sharing a sort value would otherwise
        # page unpredictably.
        return (ordering, Order.id.asc())

    def _load_options(self) -> Sequence[Any]:
        return (_ITEMS,)

    def _distinct_rows(self) -> bool:
        return True

    def _to_dto(self, row: Order) -> OrderOut:
        return to_order_out(row)


class OrdersService:
    """Reads and writes orders, their lines and their status."""

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService | None = None,
        events: DomainEventPublisher | None = None,
        stock: OrdersStockPort | None = None,
    ) -> None:
        self._session = session
        # The trail is written on the caller's session, which is what keeps a
        # business change and its audit entry in one transaction.
        self._audit = audit if audit is not None else AuditService(session)
        self._events: DomainEventPublisher = events if events is not None else NoopPublisher()
        # Optional on purpose: without it a transition moves the order and
        # nothing else, so a deployment (or a unit test) with no warehouse still
        # works exactly as it did before stock existed.
        self._stock = stock

    # ------------------------------------------------------------------ read

    async def list(self, access: OrderAccess, query: OrderListParams) -> tuple[list[OrderOut], int]:
        """One page of orders the caller is allowed to see."""
        return await _OrderListPage(self._session, access).run(query)

    async def get_by_id(self, access: OrderAccess, order_id: uuid.UUID) -> OrderOut:
        return to_order_out(await self._require_order(access, order_id))

    # ----------------------------------------------------------------- write

    async def create(self, access: OrderAccess, data: CreateOrderRequest) -> OrderOut:
        owner_id = data.owner_id if data.owner_id is not None else access.actor_id
        _ensure_owner_access(access, owner_id)
        currency = data.currency if data.currency is not None else DEFAULT_CURRENCY

        await self._require_contact(access, data.contact_id)
        await self._require_deal(access, data.deal_id)
        lines = await self._resolve_lines(currency, data.items or [])
        totals = calculate_order_totals(
            [line.line_total for line in lines],
            data.discount_total if data.discount_total is not None else ZERO_MONEY,
            data.tax_total if data.tax_total is not None else ZERO_MONEY,
        )

        order_id = await self._insert_order(data, owner_id, currency, totals, lines)
        created = to_order_out(await self._require_order(access, order_id))

        await self._record(access, "order.created", order_id, {"after": _dump(created)})
        self._announce(access, "order.created", order_id, {"after": _dump(created)})
        return created

    async def duplicate(self, access: OrderAccess, order_id: uuid.UUID) -> OrderOut:
        """Builds a fresh DRAFT order from the lines of an existing one.

        The source may be in any status — duplicating is not a transition, it is
        a new order that happens to start from the same lines. It goes through
        the very same path as a plain ``create``, so it gets a fresh number, a
        version of its own, and lines re-priced from the catalogue as it stands
        now rather than at whatever price the source paid.
        """
        source = await self._require_order(access, order_id)
        data = CreateOrderRequest(
            owner_id=source.owner_id,
            contact_id=source.contact_id,
            currency=source.currency,
            items=[
                OrderItemRequest(product_id=item.product_id, quantity=item.quantity)
                for item in source.items
            ],
        )
        return await self.create(access, data)

    async def update(
        self, access: OrderAccess, order_id: uuid.UUID, data: UpdateOrderRequest
    ) -> OrderOut:
        order = await self._require_order(access, order_id)
        _assert_version(order.version, data.version)
        fields = data.model_fields_set
        owner_id = data.owner_id if data.owner_id is not None else order.owner_id
        _ensure_owner_access(access, owner_id)

        self._assert_update_allowed(order, data, fields)
        await self._require_contact(access, data.contact_id)
        await self._require_deal(access, data.deal_id)

        values: dict[str, Any] = {}
        if data.owner_id is not None:
            values["owner_id"] = data.owner_id
        for field, column in (("contact_id", "contact_id"), ("deal_id", "deal_id")):
            if field in fields:
                values[column] = getattr(data, field)
        if data.currency is not None:
            values["currency"] = data.currency
        if "notes" in fields:
            values["notes"] = data.notes

        # Totals are always derived, never taken from the request body.
        totals = calculate_order_totals(
            [item.line_total for item in order.items],
            data.discount_total if data.discount_total is not None else order.discount_total,
            data.tax_total if data.tax_total is not None else order.tax_total,
        )
        before = to_order_out(order)
        after = to_order_out(await self._apply_update(access, order, values | _totals(totals)))

        payload = {"before": _dump(before), "after": _dump(after)}
        await self._record(access, "order.updated", order_id, payload)
        self._announce(access, "order.updated", order_id, payload)
        return after

    async def add_item(
        self, access: OrderAccess, order_id: uuid.UUID, data: AddOrderItemRequest
    ) -> OrderOut:
        order = await self._require_order(access, order_id)
        _assert_version(order.version, data.version)
        assert_order_editable(order.status)
        if any(item.product_id == data.product_id for item in order.items):
            raise ConflictError("This product is already on the order", ORDER_ITEM_DUPLICATE)

        lines = await self._resolve_lines(
            order.currency, [OrderItemRequest(product_id=data.product_id, quantity=data.quantity)]
        )
        line = lines[0]
        self._session.add(OrderItem(id=uuid.uuid4(), order_id=order_id, **asdict(line)))
        await self._flush_items()

        before = to_order_out(order)
        line_totals = [item.line_total for item in order.items] + [line.line_total]
        after = to_order_out(await self._rewrite_totals(access, order, line_totals))

        payload = {
            "productId": str(line.product_id),
            "before": _dump(before),
            "after": _dump(after),
        }
        await self._record(access, "order.item_added", order_id, payload)
        self._announce(access, "order.item_added", order_id, payload)
        return after

    async def update_item(
        self,
        access: OrderAccess,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        data: UpdateOrderItemRequest,
    ) -> OrderOut:
        order = await self._require_order(access, order_id)
        _assert_version(order.version, data.version)
        assert_order_editable(order.status)
        item = _require_item(order, item_id)

        # The snapshot price stays untouched: only the quantity is negotiable.
        line_total = calculate_line_total(item.unit_price, data.quantity)
        before = to_order_out(order)
        item.quantity = data.quantity
        item.line_total = line_total
        await self._flush_items()

        line_totals = [
            line_total if candidate.id == item_id else candidate.line_total
            for candidate in order.items
        ]
        after = to_order_out(await self._rewrite_totals(access, order, line_totals))

        payload = {"itemId": str(item_id), "before": _dump(before), "after": _dump(after)}
        await self._record(access, "order.item_updated", order_id, payload)
        # Reusing `order.updated`: a quantity change is an order-level change and
        # the payload carries the full before/after line-up anyway.
        self._announce(access, "order.updated", order_id, payload)
        return after

    async def remove_item(
        self, access: OrderAccess, order_id: uuid.UUID, item_id: uuid.UUID, version: int
    ) -> OrderOut:
        order = await self._require_order(access, order_id)
        _assert_version(order.version, version)
        assert_order_editable(order.status)
        item = _require_item(order, item_id)

        before = to_order_out(order)
        line_totals = [candidate.line_total for candidate in order.items if candidate.id != item_id]
        await self._session.delete(item)
        await self._flush_items()
        after = to_order_out(await self._rewrite_totals(access, order, line_totals))

        payload = {"itemId": str(item_id), "before": _dump(before), "after": _dump(after)}
        await self._record(access, "order.item_removed", order_id, payload)
        self._announce(access, "order.item_removed", order_id, payload)
        return after

    async def transition(
        self, access: OrderAccess, order_id: uuid.UUID, data: TransitionOrderRequest
    ) -> OrderOut:
        """Moves the order to the next stage, and the stock with it."""
        order = await self._require_order(access, order_id)
        _assert_version(order.version, data.version)
        assert_order_status_transition(order.status, data.status)
        assert_order_has_items(order.status, len(order.items))

        effect = stock_effect_for_transition(order.status, data.status)
        before = to_order_out(order)
        values: dict[str, Any] = {"status": data.status}
        if data.status == OrderStatus.CONFIRMED:
            # Confirmation is the moment the order is actually placed.
            values["placed_at"] = datetime.now(tz=UTC)

        # The order write goes first so that a stale version is rejected before
        # any stock is touched; the stock then moves on the same session, so a
        # reservation that cannot be met rolls the status change back with it.
        updated = await self._apply_update(access, order, values)
        publishers = (
            await self._apply_stock_effect(access, before, effect) if effect is not None else []
        )

        after = to_order_out(updated)
        payload = {"before": _dump(before), "after": _dump(after)}
        await self._record(access, "order.status_transitioned", order_id, payload)

        # The stock events belong to the warehouse module, which decides what
        # they say; the order only decides when they are safe to publish.
        for publish in publishers:
            publish()
        self._announce(
            access,
            "order.status_transitioned",
            order_id,
            {"from": before.status.value, "to": after.status.value, "after": _dump(after)},
        )
        return after

    async def delete(self, access: OrderAccess, order_id: uuid.UUID, version: int) -> None:
        """Soft-deletes the order; the lines and their history stay readable."""
        order = await self._require_order(access, order_id)
        _assert_version(order.version, version)
        deleted_at = datetime.now(tz=UTC)
        before = to_order_out(order)
        await self._apply_update(access, order, {"deleted_at": deleted_at}, reload=False)

        payload = {
            "before": _dump(before),
            "after": {"deletedAt": deleted_at.isoformat(), "version": version + 1},
        }
        await self._record(access, "order.deleted", order_id, payload)
        self._announce(access, "order.deleted", order_id, {"id": str(order_id)})

    # ------------------------------------------------------------- internals

    def _visible(self, access: OrderAccess, order_id: uuid.UUID) -> Select[tuple[Order]]:
        return (
            select(Order)
            .options(_ITEMS)
            .where(
                Order.id == order_id,
                Order.deleted_at.is_(None),
                *_owner_criteria(access),
            )
            # The row is re-read after a Core update, which bypasses the ORM;
            # without this the session would hand back the stale copy it holds.
            .execution_options(populate_existing=True)
        )

    async def _require_order(self, access: OrderAccess, order_id: uuid.UUID) -> Order:
        result = await self._session.execute(self._visible(access, order_id))
        order = result.scalars().unique().one_or_none()
        if order is None:
            # An order that exists but belongs to somebody else is reported as
            # missing: a narrower scope must not become a way to probe for ids.
            raise NotFoundError("Order not found", ORDER_NOT_FOUND)
        return order

    async def _require_contact(self, access: OrderAccess, contact_id: uuid.UUID | None) -> None:
        if contact_id is None:
            return
        criteria: Criteria = [Contact.id == contact_id, Contact.deleted_at.is_(None)]
        if access.scope == PermissionScope.OWN:
            criteria.append(Contact.owner_id == access.actor_id)
        if await self._session.scalar(select(Contact.id).where(*criteria)) is None:
            raise NotFoundError("Contact not found", CONTACT_NOT_FOUND)

    async def _require_deal(self, access: OrderAccess, deal_id: uuid.UUID | None) -> None:
        if deal_id is None:
            return
        criteria: Criteria = [Deal.id == deal_id, Deal.deleted_at.is_(None)]
        if access.scope == PermissionScope.OWN:
            criteria.append(Deal.owner_id == access.actor_id)
        if await self._session.scalar(select(Deal.id).where(*criteria)) is None:
            raise NotFoundError("Deal not found", DEAL_NOT_FOUND)

    async def _resolve_lines(self, currency: str, requests: Sequence[OrderItemRequest]) -> Lines:
        """Turns product references into priced order lines.

        The sku, the name and the price are snapshotted as they are *now*: a
        later catalogue change must not rewrite the history of an order that has
        already been placed.
        """
        if not requests:
            return []
        product_ids = list({request.product_id for request in requests})
        result = await self._session.execute(
            select(Product).where(Product.id.in_(product_ids), Product.deleted_at.is_(None))
        )
        by_id = {product.id: product for product in result.scalars().unique().all()}

        lines: Lines = []
        for request in requests:
            product = by_id.get(request.product_id)
            if product is None:
                raise NotFoundError("Product not found", PRODUCT_NOT_FOUND)
            if not product.is_active:
                raise ConflictError(
                    "Product is not available for ordering",
                    PRODUCT_INACTIVE,
                    {"productId": str(product.id)},
                )
            if product.currency != currency:
                raise ConflictError(
                    "Order and product currencies differ",
                    ORDER_CURRENCY_MISMATCH,
                    {
                        "productId": str(product.id),
                        "productCurrency": product.currency,
                        "orderCurrency": currency,
                    },
                )
            unit_price = normalize_money(product.unit_price)
            lines.append(
                _OrderLine(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    quantity=request.quantity,
                    unit_price=unit_price,
                    line_total=calculate_line_total(unit_price, request.quantity),
                )
            )
        return lines

    async def _insert_order(
        self,
        data: CreateOrderRequest,
        owner_id: uuid.UUID,
        currency: str,
        totals: OrderTotals,
        lines: Sequence[_OrderLine],
    ) -> uuid.UUID:
        """Inserts the order, redrawing its number if that number was taken.

        The insert runs inside a savepoint so a collision can be retried without
        losing the surrounding transaction, which a failed statement would
        otherwise leave unusable.
        """
        for attempt in range(1, ORDER_NUMBER_ATTEMPTS + 1):
            order_id = uuid.uuid4()
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        Order(
                            id=order_id,
                            order_number=generate_order_number(),
                            owner_id=owner_id,
                            contact_id=data.contact_id,
                            deal_id=data.deal_id,
                            status=OrderStatus.DRAFT,
                            currency=currency,
                            notes=data.notes,
                            **_totals(totals),
                        )
                    )
                    for line in lines:
                        self._session.add(
                            OrderItem(id=uuid.uuid4(), order_id=order_id, **asdict(line))
                        )
                    await self._session.flush()
            except IntegrityError as error:
                if not _is_order_number_conflict(error):
                    raise ConflictError(
                        "This product is already on the order", ORDER_ITEM_DUPLICATE
                    ) from error
                if attempt == ORDER_NUMBER_ATTEMPTS:
                    raise ConflictError(
                        "Could not allocate an order number", ORDER_NUMBER_UNAVAILABLE
                    ) from error
            else:
                return order_id
        raise ConflictError("Could not allocate an order number", ORDER_NUMBER_UNAVAILABLE)

    async def _flush_items(self) -> None:
        """Surfaces the one-product-per-order constraint as the conflict it is."""
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(
                "This product is already on the order", ORDER_ITEM_DUPLICATE
            ) from error

    async def _apply_update(
        self,
        access: OrderAccess,
        order: Order,
        values: Mapping[str, Any],
        *,
        reload: bool = True,
    ) -> Order:
        """Writes the order under optimistic locking and bumps its version.

        The previously read version *and* status are part of the predicate, so a
        racing writer who already moved the order loses this write rather than
        silently overwriting theirs.
        """
        result = await self._session.execute(
            update(Order)
            .where(
                Order.id == order.id,
                Order.version == order.version,
                Order.status == order.status,
                Order.deleted_at.is_(None),
                *_owner_criteria(access),
            )
            .values(**values, version=Order.version + 1)
            .execution_options(synchronize_session=False)
        )
        # `execute` is typed as returning a plain Result; only the cursor variant
        # carries the row count an optimistic-locking check needs.
        if cast("CursorResult[Any]", result).rowcount != 1:
            raise StaleVersionError(
                "Order was modified by another request", ORDER_CONCURRENT_MODIFICATION
            )
        return await self._require_order(access, order.id) if reload else order

    async def _rewrite_totals(
        self, access: OrderAccess, order: Order, line_totals: Sequence[Decimal]
    ) -> Order:
        """Shared tail of every line mutation: recompute totals, bump the order."""
        totals = calculate_order_totals(line_totals, order.discount_total, order.tax_total)
        return await self._apply_update(access, order, _totals(totals))

    def _assert_update_allowed(
        self, order: Order, data: UpdateOrderRequest, fields: set[str]
    ) -> None:
        """Money reshapes the order itself, so it follows the draft-only rule.

        Descriptive fields stay editable until the order reaches a terminal
        status; the amounts and the currency do not.
        """
        touches_money = bool(fields & {"discount_total", "tax_total", "currency"})
        terminal = order.status in (OrderStatus.FULFILLED, OrderStatus.CANCELLED)
        if touches_money or terminal:
            assert_order_editable(order.status)
        if data.currency is not None and data.currency != order.currency and order.items:
            raise ConflictError(
                "Currency cannot change while the order has items",
                ORDER_CURRENCY_MISMATCH,
                {"orderCurrency": order.currency, "requestedCurrency": data.currency},
            )

    async def _apply_stock_effect(
        self, access: OrderAccess, order: OrderOut, effect: OrderStockEffect
    ) -> Publishers:
        """Moves stock for every line, on the session carrying the status change.

        Nothing is published here: the returned callbacks are invoked by the
        caller once the operation has succeeded. The lines are walked one after
        another rather than concurrently, because they share a single session
        and a database transaction serves one statement at a time.
        """
        if self._stock is None:
            return []
        warehouse_id = await self._stock.resolve_warehouse_id(self._session)
        if warehouse_id is None:
            raise ConflictError(
                "No warehouse is configured to hold stock for orders",
                WAREHOUSE_NOT_CONFIGURED,
            )

        operations = self._stock.operations
        operation = {
            "reserve": operations.reserve,
            "release": operations.release,
            "issue": operations.issue,
        }[effect]

        publishers: Publishers = []
        for line in order.items:
            data = OrderStockInput(
                warehouse_id=warehouse_id,
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type=ORDER_STOCK_REFERENCE_TYPE,
                reference_id=order.id,
                # Fulfilment hands over goods the order already holds a
                # reservation for, so that reservation is consumed by the very
                # movement that issues them.
                from_reservation=effect == "issue",
            )
            try:
                change = await operation(self._session, access, data)
            except AppError as error:
                raise _attributed_to_line(error, order.id, line) from error
            publishers.append(change.publish_committed)
        return publishers

    async def _record(
        self, access: OrderAccess, action: str, order_id: uuid.UUID, changes: Any
    ) -> None:
        await self._audit.record(
            AuditEvent(
                action=action,
                entity_type=ORDER_ENTITY_TYPE,
                entity_id=order_id,
                actor_id=access.actor_id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )

    def _announce(
        self, access: OrderAccess, event_type: str, order_id: uuid.UUID, payload: Any
    ) -> None:
        """Tells the secondary consumers what changed.

        The publisher contract forbids throwing, but the primary path is guarded
        anyway: a change the caller is about to see as successful must not be
        reported as a failure because a listener misbehaved.
        """
        try:
            self._events.publish(
                DomainEvent(
                    event_type=event_type,
                    entity_type=ORDER_ENTITY_TYPE,
                    entity_id=str(order_id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                )
            )
        except Exception:
            return


def _totals(totals: OrderTotals) -> dict[str, Decimal]:
    """The four derived amounts, spelled as columns."""
    return {
        "subtotal": totals.subtotal,
        "discount_total": totals.discount_total,
        "tax_total": totals.tax_total,
        "total": totals.total,
    }


def _assert_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise StaleVersionError(
            "Order was modified by another request", ORDER_CONCURRENT_MODIFICATION
        )


def _ensure_owner_access(access: OrderAccess, owner_id: uuid.UUID) -> None:
    """A caller holding ``OWN`` may not hand an order to somebody else."""
    if access.scope == PermissionScope.OWN and owner_id != access.actor_id:
        raise ForbiddenError()


def _require_item(order: Order, item_id: uuid.UUID) -> OrderItem:
    for item in order.items:
        if item.id == item_id:
            return item
    raise NotFoundError("Order item not found", ORDER_ITEM_NOT_FOUND)


def _attributed_to_line(error: AppError, order_id: uuid.UUID, line: OrderItemOut) -> AppError:
    """Re-labels a stock failure with the line that caused it.

    A rejected confirmation should tell the caller *which* product blocked it,
    not merely that something was short.
    """
    details = error.details if isinstance(error.details, dict) else {}
    return AppError(
        error.message,
        error.status_code,
        error.code,
        {
            **details,
            "orderId": str(order_id),
            "productId": str(line.product_id),
            "quantity": line.quantity,
        },
    )
