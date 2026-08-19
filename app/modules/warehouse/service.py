"""Warehouse administration and the arithmetic of stock.

The interesting half of this module is a single rule: ``quantity_on_hand`` and
``quantity_reserved`` may never go negative, and reserved units may never exceed
the units actually on the shelf. Every operation therefore builds a *plan*,
checks the plan against the level it just read, and only then writes.

The write itself is pinned to the version that was read. A plain read-then-write
is unsafe: two requests can both see five units with nothing reserved, both
conclude that five units are available, and both write ``quantity_reserved = 5``
— the second silently overwrites the first and the same five units are promised
twice. Conditioning the update on the version turns the losing write into an
affected-row count of zero, which is reported as a retryable 409 instead of a
lost update.

Nothing here opens a transaction. The session belongs to the caller — a request
handler, or another module that needs its own write and this stock change to
commit together — so a movement and whatever caused it can never end up on
different sides of a rollback.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, Executable, event, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.db.enums import StockMovementType
from app.db.models.warehouse import StockLevel, StockMovement, Warehouse
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.warehouse.schemas import (
    AdjustStockRequest,
    CreateWarehouseRequest,
    IssueStockRequest,
    MovementListParams,
    ReceiveStockRequest,
    ReleaseStockRequest,
    ReserveStockRequest,
    StockLevelOut,
    StockListParams,
    StockMovementOut,
    UpdateWarehouseRequest,
    WarehouseListParams,
    WarehouseOut,
)
from app.modules.warehouse.types import (
    INVALID_STOCK_ADJUSTMENT,
    PRODUCT_NOT_FOUND,
    STOCK_ADJUSTMENT_NOTE_REQUIRED,
    STOCK_ENTITY_TYPE,
    STOCK_LEVEL_NOT_FOUND,
    WAREHOUSE_CODE_IMMUTABLE,
    WAREHOUSE_CODE_TAKEN,
    WAREHOUSE_ENTITY_TYPE,
    WAREHOUSE_NOT_FOUND,
    InsufficientReservationError,
    InsufficientStockError,
    MovementPlan,
    StockActor,
    StockAdjustmentInput,
    StockOperationInput,
    StockVersionConflictError,
    WarehouseAccess,
    WarehouseInactiveError,
)

_LEVEL_COLUMNS = (
    StockLevel.id,
    StockLevel.quantity_on_hand,
    StockLevel.quantity_reserved,
    StockLevel.version,
    StockLevel.created_at,
    StockLevel.updated_at,
)


def to_warehouse_out(row: Warehouse) -> WarehouseOut:
    return WarehouseOut(
        id=row.id,
        code=row.code,
        name=row.name,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_stock_level_out(row: StockLevel) -> StockLevelOut:
    return StockLevelOut(
        id=row.id,
        warehouse_id=row.warehouse_id,
        product_id=row.product_id,
        quantity_on_hand=row.quantity_on_hand,
        quantity_reserved=row.quantity_reserved,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_movement_out(row: StockMovement) -> StockMovementOut:
    return StockMovementOut(
        id=row.id,
        warehouse_id=row.warehouse_id,
        product_id=row.product_id,
        type=row.type,
        quantity=row.quantity,
        reference_type=row.reference_type,
        reference_id=row.reference_id,
        actor_id=row.actor_id,
        note=row.note,
        created_at=row.created_at,
    )


def next_quantities(on_hand: int, reserved: int, plan: MovementPlan) -> tuple[int, int]:
    """Rejects every impossible outcome before a single row is touched.

    The order of the checks is deliberate: a reservation that would go negative
    is reported as a reservation problem, while anything that would leave
    reserved units without stock behind them is an oversell.
    """
    next_on_hand = on_hand + plan.on_hand_delta
    next_reserved = reserved + plan.reserved_delta
    if next_reserved < 0:
        raise InsufficientReservationError()
    if next_on_hand < 0:
        raise InsufficientStockError()
    if next_reserved > next_on_hand:
        raise InsufficientStockError()
    return next_on_hand, next_reserved


def _optional_note(data: object) -> str | None:
    """Reads a note if the caller's structure carries one at all."""
    note = getattr(data, "note", None)
    return note if isinstance(note, str) and note.strip() else None


def receive_plan(data: StockOperationInput) -> MovementPlan:
    return MovementPlan(
        movement_type=StockMovementType.RECEIPT,
        event_type="stock.received",
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=data.quantity,
        on_hand_delta=data.quantity,
        reserved_delta=0,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        note=_optional_note(data),
    )


def issue_plan(data: StockOperationInput) -> MovementPlan:
    """An issue removes units; against a reservation it frees them as well.

    Without that second delta the row would breach the database rule that
    reserved units can never exceed the units on hand.
    """
    from_reservation = bool(getattr(data, "from_reservation", False))
    return MovementPlan(
        movement_type=StockMovementType.ISSUE,
        event_type="stock.issued",
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=data.quantity,
        on_hand_delta=-data.quantity,
        reserved_delta=-data.quantity if from_reservation else 0,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        note=_optional_note(data),
    )


def reserve_plan(data: StockOperationInput) -> MovementPlan:
    return MovementPlan(
        movement_type=StockMovementType.RESERVATION,
        event_type="stock.reserved",
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=data.quantity,
        on_hand_delta=0,
        reserved_delta=data.quantity,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        note=_optional_note(data),
    )


def release_plan(data: StockOperationInput) -> MovementPlan:
    return MovementPlan(
        movement_type=StockMovementType.RELEASE,
        event_type="stock.released",
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=data.quantity,
        on_hand_delta=0,
        reserved_delta=-data.quantity,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        note=_optional_note(data),
    )


def adjust_plan(data: StockAdjustmentInput) -> MovementPlan:
    """Refuses a correction that records nothing or explains nothing.

    The schema rejects both cases already; the guard is repeated because a
    caller reaching the operations port never passed through the schema.
    """
    if data.delta == 0:
        raise AppError("Adjustment delta must not be zero", 400, INVALID_STOCK_ADJUSTMENT)
    note = data.note.strip()
    if not note:
        raise AppError("Adjustment requires a note", 400, STOCK_ADJUSTMENT_NOTE_REQUIRED)
    return MovementPlan(
        movement_type=StockMovementType.ADJUSTMENT,
        event_type="stock.adjusted",
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=abs(data.delta),
        on_hand_delta=data.delta,
        reserved_delta=0,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        note=note,
    )


class StockChange:
    """The outcome of a movement applied on somebody else's session.

    The event is built but not published: the transaction has not committed yet
    and may still roll back, so the caller announces the change by calling
    ``publish_committed`` once its own work has succeeded.
    """

    __slots__ = ("_publish", "level", "movement")

    def __init__(
        self, level: StockLevelOut, movement: StockMovementOut, publish: Callable[[], None]
    ) -> None:
        self.level = level
        self.movement = movement
        self._publish = publish

    def publish_committed(self) -> None:
        """Announces the movement; call only after the transaction committed."""
        self._publish()


def publish_after_commit(session: AsyncSession, publish: Callable[[], None]) -> None:
    """Defers an announcement until the session's transaction has committed.

    The request session commits after the handler returns, so publishing inside
    the handler would announce a change that a later failure could still undo.
    A session without the ORM event bus — a stand-in in a unit test — publishes
    immediately, which is the only thing it can honestly do.
    """
    sync_session = getattr(session, "sync_session", None)
    if sync_session is None:
        publish()
        return

    def _announce(_session: Any) -> None:
        publish()

    event.listen(sync_session, "after_commit", _announce, once=True)


def _announcer(publisher: DomainEventPublisher, domain_event: DomainEvent) -> Callable[[], None]:
    """Wraps publication so a broken listener cannot fail a committed change."""

    def publish() -> None:
        with contextlib.suppress(Exception):
            publisher.publish(domain_event)

    return publish


def _map_integrity_error(error: IntegrityError) -> AppError:
    """Translates the database's last line of defence into a domain failure.

    The arithmetic guards reject an oversell before anything is written, so a
    CHECK that still fires describes a path nobody anticipated — but it is a
    business conflict all the same, never a server fault.
    """
    text = str(error.orig or error).lower()
    if "foreign key" in text:
        # The warehouse is verified before the write, so the only other
        # reference a movement carries is the product.
        return NotFoundError("Product not found", PRODUCT_NOT_FOUND)
    if "unique" in text or "duplicate key" in text:
        # Two first-ever movements for the same pair raced; the loser retries.
        return StockVersionConflictError()
    if "quantity_reserved" in text:
        return InsufficientReservationError()
    if "check constraint" in text:
        return InsufficientStockError()
    return ConflictError(str(error.orig or error))


async def _require_writable_warehouse(session: AsyncSession, warehouse_id: uuid.UUID) -> None:
    is_active = (
        await session.execute(select(Warehouse.is_active).where(Warehouse.id == warehouse_id))
    ).scalar_one_or_none()
    if is_active is None:
        raise NotFoundError("Warehouse not found", WAREHOUSE_NOT_FOUND)
    if not is_active:
        raise WarehouseInactiveError()


async def _write_level(
    session: AsyncSession,
    existing: StockLevel | None,
    plan: MovementPlan,
    quantities: tuple[int, int],
) -> StockLevelOut:
    on_hand, reserved = quantities
    statement: Executable
    if existing is None:
        statement = (
            insert(StockLevel)
            .values(
                warehouse_id=plan.warehouse_id,
                product_id=plan.product_id,
                quantity_on_hand=on_hand,
                quantity_reserved=reserved,
            )
            .returning(*_LEVEL_COLUMNS)
        )
    else:
        # The version the guards reasoned about is part of the WHERE clause, so
        # a level that moved in between updates nothing at all.
        statement = (
            update(StockLevel)
            .where(StockLevel.id == existing.id, StockLevel.version == existing.version)
            .values(
                quantity_on_hand=on_hand,
                quantity_reserved=reserved,
                version=StockLevel.version + 1,
            )
            .returning(*_LEVEL_COLUMNS)
        )

    try:
        row = (await session.execute(statement)).one_or_none()
    except IntegrityError as error:
        raise _map_integrity_error(error) from error

    if row is None:
        raise StockVersionConflictError()

    return StockLevelOut(
        id=row.id,
        warehouse_id=plan.warehouse_id,
        product_id=plan.product_id,
        quantity_on_hand=row.quantity_on_hand,
        quantity_reserved=row.quantity_reserved,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _write_movement(
    session: AsyncSession, actor_id: uuid.UUID, plan: MovementPlan
) -> StockMovementOut:
    """Appends the ledger row that explains the change to the level."""
    statement = (
        insert(StockMovement)
        .values(
            warehouse_id=plan.warehouse_id,
            product_id=plan.product_id,
            type=plan.movement_type,
            quantity=plan.quantity,
            reference_type=plan.reference_type,
            reference_id=plan.reference_id,
            actor_id=actor_id,
            note=plan.note,
        )
        .returning(StockMovement.id, StockMovement.created_at)
    )
    try:
        row = (await session.execute(statement)).one()
    except IntegrityError as error:
        raise _map_integrity_error(error) from error

    return StockMovementOut(
        id=row.id,
        warehouse_id=plan.warehouse_id,
        product_id=plan.product_id,
        type=plan.movement_type,
        quantity=plan.quantity,
        reference_type=plan.reference_type,
        reference_id=plan.reference_id,
        actor_id=actor_id,
        note=plan.note,
        created_at=row.created_at,
    )


def _dump(model: StockLevelOut | StockMovementOut | WarehouseOut | None) -> Any:
    return None if model is None else model.model_dump(mode="json", by_alias=True)


async def apply_stock_movement(
    session: AsyncSession,
    publisher: DomainEventPublisher,
    access: StockActor,
    plan: MovementPlan,
) -> StockChange:
    """Applies one movement on the session the caller supplied.

    Guard, level, ledger row and audit entry, in that order and on one session,
    so the four either all become visible or none of them do.
    """
    await _require_writable_warehouse(session, plan.warehouse_id)

    existing = (
        await session.execute(
            select(StockLevel).where(
                StockLevel.warehouse_id == plan.warehouse_id,
                StockLevel.product_id == plan.product_id,
            )
        )
    ).scalar_one_or_none()

    # A pair that has never been stocked behaves exactly like an empty one, so
    # an issue or a reservation against it is refused without creating a row.
    before = to_stock_level_out(existing) if existing is not None else None
    quantities = next_quantities(
        existing.quantity_on_hand if existing is not None else 0,
        existing.quantity_reserved if existing is not None else 0,
        plan,
    )

    after = await _write_level(session, existing, plan, quantities)
    movement = await _write_movement(session, access.actor_id, plan)

    await AuditService(session).record(
        AuditEvent(
            action=plan.event_type,
            entity_type=STOCK_ENTITY_TYPE,
            entity_id=after.id,
            actor_id=access.actor_id,
            changes={"before": _dump(before), "after": _dump(after)},
            metadata={
                "movementId": str(movement.id),
                "type": plan.movement_type.value,
                "quantity": plan.quantity,
                "referenceType": plan.reference_type,
                "referenceId": None if plan.reference_id is None else str(plan.reference_id),
            },
            ip_address=getattr(access, "ip_address", None),
        )
    )

    return StockChange(
        after,
        movement,
        _announcer(
            publisher,
            DomainEvent(
                event_type=plan.event_type,
                entity_type=STOCK_ENTITY_TYPE,
                entity_id=str(after.id),
                actor_id=str(access.actor_id),
                payload={
                    "before": _dump(before),
                    "after": _dump(after),
                    "movement": _dump(movement),
                },
            ),
        ),
    )


class _WarehousePage(PagedQuery[Warehouse, WarehouseListParams, WarehouseOut]):
    def _model(self) -> type[Warehouse]:
        return Warehouse

    def _build_filters(self, params: WarehouseListParams) -> list[ColumnElement[bool]]:
        return (
            FilterBuilder()
            .flag(Warehouse.is_active, params.is_active)
            .search(params.search, [Warehouse.code, Warehouse.name])
            .build()
        )

    def _order_by(self, _params: WarehouseListParams) -> tuple[ColumnElement[Any], ...]:
        return (Warehouse.code.asc(),)

    def _to_dto(self, row: Warehouse) -> WarehouseOut:
        return to_warehouse_out(row)


class _StockPage(PagedQuery[StockLevel, StockListParams, StockLevelOut]):
    def _model(self) -> type[StockLevel]:
        return StockLevel

    def _build_filters(self, params: StockListParams) -> list[ColumnElement[bool]]:
        return (
            FilterBuilder()
            .equals(StockLevel.warehouse_id, params.warehouse_id)
            .equals(StockLevel.product_id, params.product_id)
            .range(StockLevel.quantity_on_hand, maximum=params.low_stock_threshold)
            .build()
        )

    def _order_by(self, _params: StockListParams) -> tuple[ColumnElement[Any], ...]:
        # Scarcest first: the page a stock report opens on is the one that
        # needs attention.
        return (StockLevel.quantity_on_hand.asc(), StockLevel.id.asc())

    def _to_dto(self, row: StockLevel) -> StockLevelOut:
        return to_stock_level_out(row)


class _MovementPage(PagedQuery[StockMovement, MovementListParams, StockMovementOut]):
    def _model(self) -> type[StockMovement]:
        return StockMovement

    def _build_filters(self, params: MovementListParams) -> list[ColumnElement[bool]]:
        return (
            FilterBuilder()
            .equals(StockMovement.warehouse_id, params.warehouse_id)
            .equals(StockMovement.product_id, params.product_id)
            .equals(StockMovement.type, params.type)
            .equals(StockMovement.reference_type, params.reference_type)
            .equals(StockMovement.reference_id, params.reference_id)
            .range(StockMovement.created_at, params.created_from, params.created_to)
            .build()
        )

    def _order_by(self, _params: MovementListParams) -> tuple[ColumnElement[Any], ...]:
        # By id as well as time: two movements written in the same millisecond
        # would otherwise page unpredictably.
        return (StockMovement.created_at.desc(), StockMovement.id.desc())

    def _to_dto(self, row: StockMovement) -> StockMovementOut:
        return to_movement_out(row)


class WarehouseService:
    """Warehouse administration, stock reads and the five stock operations."""

    def __init__(
        self, session: AsyncSession, publisher: DomainEventPublisher | None = None
    ) -> None:
        self._session = session
        self._audit = AuditService(session)
        self._publisher: DomainEventPublisher = (
            publisher if publisher is not None else NoopPublisher()
        )

    async def list_warehouses(self, params: WarehouseListParams) -> tuple[list[WarehouseOut], int]:
        return await _WarehousePage(self._session).run(params)

    async def get_warehouse(self, warehouse_id: uuid.UUID) -> WarehouseOut:
        return to_warehouse_out(await self._require_warehouse(warehouse_id))

    async def create_warehouse(
        self, access: WarehouseAccess, data: CreateWarehouseRequest
    ) -> WarehouseOut:
        taken = await self._session.scalar(select(Warehouse.id).where(Warehouse.code == data.code))
        if taken is not None:
            raise ConflictError("A warehouse with this code already exists", WAREHOUSE_CODE_TAKEN)

        row = Warehouse(
            code=data.code,
            name=data.name,
            is_active=True if data.is_active is None else data.is_active,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(
                "A warehouse with this code already exists", WAREHOUSE_CODE_TAKEN
            ) from error

        created = await self.get_warehouse(row.id)
        await self._audit.record(
            AuditEvent(
                action="warehouse.created",
                entity_type=WAREHOUSE_ENTITY_TYPE,
                entity_id=created.id,
                actor_id=access.actor_id,
                changes={"after": _dump(created)},
                ip_address=access.ip_address,
            )
        )
        self._announce_warehouse("warehouse.created", access, created, {"after": _dump(created)})
        return created

    async def update_warehouse(
        self, access: WarehouseAccess, warehouse_id: uuid.UUID, data: UpdateWarehouseRequest
    ) -> WarehouseOut:
        row = await self._require_warehouse(warehouse_id)
        before = to_warehouse_out(row)

        # The code identifies the warehouse in every movement ever recorded
        # against it, so it is fixed once the warehouse exists.
        if data.code is not None and data.code != row.code:
            raise AppError(
                "Warehouse code cannot be changed after creation", 400, WAREHOUSE_CODE_IMMUTABLE
            )
        if data.name is not None:
            row.name = data.name
        if data.is_active is not None:
            row.is_active = data.is_active
        await self._session.flush()

        after = await self.get_warehouse(warehouse_id)
        changes = {"before": _dump(before), "after": _dump(after)}
        await self._audit.record(
            AuditEvent(
                action="warehouse.updated",
                entity_type=WAREHOUSE_ENTITY_TYPE,
                entity_id=after.id,
                actor_id=access.actor_id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )
        self._announce_warehouse("warehouse.updated", access, after, changes)
        return after

    async def list_stock(self, params: StockListParams) -> tuple[list[StockLevelOut], int]:
        return await _StockPage(self._session).run(params)

    async def get_stock(self, warehouse_id: uuid.UUID, product_id: uuid.UUID) -> StockLevelOut:
        row = (
            await self._session.execute(
                select(StockLevel).where(
                    StockLevel.warehouse_id == warehouse_id, StockLevel.product_id == product_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Stock level not found", STOCK_LEVEL_NOT_FOUND)
        return to_stock_level_out(row)

    async def list_movements(
        self, params: MovementListParams
    ) -> tuple[list[StockMovementOut], int]:
        return await _MovementPage(self._session).run(params)

    async def receive(self, access: WarehouseAccess, data: ReceiveStockRequest) -> StockLevelOut:
        return await self._apply(access, receive_plan(data))

    async def issue(self, access: WarehouseAccess, data: IssueStockRequest) -> StockLevelOut:
        return await self._apply(access, issue_plan(data))

    async def reserve(self, access: WarehouseAccess, data: ReserveStockRequest) -> StockLevelOut:
        return await self._apply(access, reserve_plan(data))

    async def release(self, access: WarehouseAccess, data: ReleaseStockRequest) -> StockLevelOut:
        return await self._apply(access, release_plan(data))

    async def adjust(self, access: WarehouseAccess, data: AdjustStockRequest) -> StockLevelOut:
        return await self._apply(access, adjust_plan(data))

    async def _apply(self, access: WarehouseAccess, plan: MovementPlan) -> StockLevelOut:
        change = await apply_stock_movement(self._session, self._publisher, access, plan)
        publish_after_commit(self._session, change.publish_committed)
        return change.level

    async def _require_warehouse(self, warehouse_id: uuid.UUID) -> Warehouse:
        row = (
            await self._session.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Warehouse not found", WAREHOUSE_NOT_FOUND)
        return row

    def _announce_warehouse(
        self,
        event_type: str,
        access: WarehouseAccess,
        warehouse: WarehouseOut,
        payload: dict[str, Any],
    ) -> None:
        publish_after_commit(
            self._session,
            _announcer(
                self._publisher,
                DomainEvent(
                    event_type=event_type,
                    entity_type=WAREHOUSE_ENTITY_TYPE,
                    entity_id=str(warehouse.id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                ),
            ),
        )


__all__ = [
    "StockChange",
    "WarehouseService",
    "adjust_plan",
    "apply_stock_movement",
    "issue_plan",
    "next_quantities",
    "publish_after_commit",
    "receive_plan",
    "release_plan",
    "reserve_plan",
    "to_movement_out",
    "to_stock_level_out",
    "to_warehouse_out",
]
