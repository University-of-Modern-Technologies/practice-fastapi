"""The stock port as another module drives it.

Every case here runs on a stand-in session, because what is being checked is the
sequence a movement performs: the guard, the version-pinned write, the ledger
row, the audit entry — and that the event waits for the caller's commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, VersionConflictError
from app.db.models.warehouse import StockLevel
from app.events.types import DomainEvent
from app.modules.warehouse.operations import create_stock_operations
from app.modules.warehouse.types import (
    INSUFFICIENT_STOCK,
    STOCK_CONCURRENT_MODIFICATION,
    WAREHOUSE_INACTIVE,
    WAREHOUSE_NOT_FOUND,
)

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
WAREHOUSE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
PRODUCT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
ORDER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
LEVEL_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
MOVEMENT_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
ACTOR_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")


@dataclass(frozen=True, slots=True)
class OrderAccess:
    """The access object another module hands over — id only, no scope."""

    actor_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class OrderStockRequest:
    """The stock request another module hands over."""

    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    reference_type: str
    reference_id: uuid.UUID
    from_reservation: bool = False


class Row:
    """A returned row; attribute access is all the service asks of it."""

    def __init__(self, **columns: Any) -> None:
        self.__dict__.update(columns)


class FakeResult:
    """One scripted answer, in every shape the service reads it in."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def one_or_none(self) -> Any:
        return self._value

    def one(self) -> Any:
        if self._value is None:
            message = "no row returned"
            raise AssertionError(message)
        return self._value


class FakeSession:
    """A session that answers from a queue and remembers what it was asked."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers = answers
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flushes = 0

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self._answers.pop(0) if self._answers else None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        # A flush is where the database fills in what it owns; the stand-in has
        # to do the same, or a row read back straight after it looks empty.
        self.flushes += 1
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
            if getattr(row, "created_at", None) is None:
                row.created_at = NOW


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def existing_level(*, on_hand: int = 10, reserved: int = 4, version: int = 3) -> StockLevel:
    return StockLevel(
        id=LEVEL_ID,
        warehouse_id=WAREHOUSE_ID,
        product_id=PRODUCT_ID,
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def written_level(*, on_hand: int, reserved: int, version: int = 4) -> Row:
    return Row(
        id=LEVEL_ID,
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def movement_row() -> Row:
    return Row(id=MOVEMENT_ID, created_at=NOW)


def session_for(*answers: Any) -> FakeSession:
    """The answers a movement consumes: warehouse, level, write, ledger row."""
    return FakeSession(list(answers))


def as_session(session: FakeSession) -> AsyncSession:
    return cast("AsyncSession", session)


def request(quantity: int = 2, *, from_reservation: bool = False) -> OrderStockRequest:
    return OrderStockRequest(
        warehouse_id=WAREHOUSE_ID,
        product_id=PRODUCT_ID,
        quantity=quantity,
        reference_type="order",
        reference_id=ORDER_ID,
        from_reservation=from_reservation,
    )


ACCESS = OrderAccess(actor_id=ACTOR_ID)


def compiled_params(statement: Any) -> dict[str, Any]:
    return dict(statement.compile().params)


async def test_a_reservation_writes_through_the_session_it_is_handed() -> None:
    session = session_for(
        True, existing_level(), written_level(on_hand=10, reserved=6), movement_row()
    )
    operations = create_stock_operations()

    change = await operations.reserve(as_session(session), ACCESS, request(2))

    assert change.level.quantity_reserved == 6
    assert change.level.quantity_available == 4
    # Warehouse, level, level write, movement write — plus the audit entry,
    # which the audit service adds to this very same session.
    assert len(session.statements) == 4
    assert session.flushes == 1


async def test_the_write_is_pinned_to_the_version_that_was_read() -> None:
    session = session_for(
        True, existing_level(version=3), written_level(on_hand=10, reserved=6), movement_row()
    )
    operations = create_stock_operations()

    await operations.reserve(as_session(session), ACCESS, request(2))

    params = compiled_params(session.statements[2])
    assert params["quantity_on_hand"] == 10
    assert params["quantity_reserved"] == 6
    # The version the guard reasoned about is part of the WHERE clause, so a
    # concurrent write cannot be overwritten.
    assert 3 in params.values()


async def test_the_caller_reference_is_carried_onto_the_ledger_row() -> None:
    session = session_for(
        True, existing_level(), written_level(on_hand=10, reserved=6), movement_row()
    )
    operations = create_stock_operations()

    change = await operations.reserve(as_session(session), ACCESS, request(2))

    params = compiled_params(session.statements[3])
    assert params["reference_type"] == "order"
    assert params["reference_id"] == ORDER_ID
    assert params["actor_id"] == ACTOR_ID
    assert change.movement.type.value == "RESERVATION"


async def test_the_event_waits_until_the_caller_says_the_transaction_committed() -> None:
    session = session_for(
        True, existing_level(), written_level(on_hand=10, reserved=6), movement_row()
    )
    publisher = RecordingPublisher()
    operations = create_stock_operations(publisher)

    change = await operations.reserve(as_session(session), ACCESS, request(2))
    assert publisher.events == []

    change.publish_committed()

    assert [event.event_type for event in publisher.events] == ["stock.reserved"]
    assert publisher.events[0].entity_type == "stock"


async def test_an_oversell_is_refused_before_anything_is_written() -> None:
    session = session_for(True, existing_level())
    publisher = RecordingPublisher()
    operations = create_stock_operations(publisher)

    with pytest.raises(AppError) as error:
        await operations.reserve(as_session(session), ACCESS, request(7))

    assert (error.value.status_code, error.value.code) == (409, INSUFFICIENT_STOCK)
    # Only the warehouse and the level were read; nothing was written.
    assert len(session.statements) == 2
    assert publisher.events == []


async def test_releasing_returns_promised_units_without_touching_the_shelf() -> None:
    session = session_for(
        True, existing_level(), written_level(on_hand=10, reserved=2), movement_row()
    )
    operations = create_stock_operations()

    await operations.release(as_session(session), ACCESS, request(2))

    params = compiled_params(session.statements[2])
    assert (params["quantity_on_hand"], params["quantity_reserved"]) == (10, 2)


async def test_issuing_against_a_reservation_consumes_both_counters() -> None:
    session = session_for(
        True, existing_level(), written_level(on_hand=6, reserved=0), movement_row()
    )
    operations = create_stock_operations()

    await operations.issue(as_session(session), ACCESS, request(4, from_reservation=True))

    params = compiled_params(session.statements[2])
    assert (params["quantity_on_hand"], params["quantity_reserved"]) == (6, 0)


async def test_a_level_that_moved_in_between_is_a_retryable_conflict() -> None:
    # The conditional update matched no row: somebody else wrote first.
    session = session_for(True, existing_level(), None)
    operations = create_stock_operations()

    with pytest.raises(VersionConflictError) as error:
        await operations.reserve(as_session(session), ACCESS, request(2))

    assert (error.value.status_code, error.value.code) == (409, STOCK_CONCURRENT_MODIFICATION)


async def test_a_deactivated_warehouse_accepts_no_movement() -> None:
    session = session_for(False)
    operations = create_stock_operations()

    with pytest.raises(AppError) as error:
        await operations.reserve(as_session(session), ACCESS, request(2))

    assert (error.value.status_code, error.value.code) == (409, WAREHOUSE_INACTIVE)
    assert len(session.statements) == 1


async def test_an_unknown_warehouse_is_a_not_found() -> None:
    session = session_for(None)
    operations = create_stock_operations()

    with pytest.raises(AppError) as error:
        await operations.reserve(as_session(session), ACCESS, request(2))

    assert (error.value.status_code, error.value.code) == (404, WAREHOUSE_NOT_FOUND)


async def test_a_pair_that_was_never_stocked_is_created_by_a_receipt() -> None:
    session = session_for(
        True, None, written_level(on_hand=5, reserved=0, version=1), movement_row()
    )
    operations = create_stock_operations()

    change = await operations.receive(as_session(session), ACCESS, request(5))

    assert change.level.quantity_on_hand == 5
    assert change.level.version == 1
    params = compiled_params(session.statements[2])
    assert params["warehouse_id"] == WAREHOUSE_ID


async def test_the_audit_entry_is_written_on_the_caller_session() -> None:
    session = session_for(
        True, existing_level(), written_level(on_hand=10, reserved=6), movement_row()
    )
    operations = create_stock_operations()

    await operations.reserve(as_session(session), ACCESS, request(2))

    # One entry, flushed but not committed: the caller still owns the
    # transaction and may still roll the whole thing back.
    assert len(session.added) == 1
    entry = session.added[0]
    assert entry.action == "stock.reserved"
    assert entry.entity_type == "stock"
    assert entry.meta["movementId"] == str(MOVEMENT_ID)


async def test_a_broken_listener_cannot_undo_a_committed_movement() -> None:
    class FailingPublisher:
        def publish(self, _event: DomainEvent) -> None:
            message = "the listener is down"
            raise RuntimeError(message)

    session = session_for(
        True, existing_level(), written_level(on_hand=10, reserved=6), movement_row()
    )
    operations = create_stock_operations(FailingPublisher())

    change = await operations.reserve(as_session(session), ACCESS, request(2))

    # The movement is already committed by the time this runs; a secondary
    # consumer must not be able to turn that into a failure.
    change.publish_committed()
