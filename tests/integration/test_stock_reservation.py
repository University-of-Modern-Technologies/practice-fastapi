"""Scenario 5 — reserving stock, against the real ledger and its constraints.

Reservation is the one operation where the application's arithmetic and the
database's own rules have to agree. The service refuses to reserve more than is
available; the table refuses to hold a row where the reserved quantity exceeds
what is on hand. Only a real server can show that the two never disagree — and
only two real transactions can show that the version guard actually guards.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.enums import PermissionScope, StockMovementType
from app.db.models.warehouse import StockLevel, StockMovement
from app.modules.warehouse.schemas import (
    ReceiveStockRequest,
    ReleaseStockRequest,
    ReserveStockRequest,
)
from app.modules.warehouse.service import WarehouseService
from app.modules.warehouse.types import (
    INSUFFICIENT_RESERVATION,
    INSUFFICIENT_STOCK,
    STOCK_CONCURRENT_MODIFICATION,
    WarehouseAccess,
)
from tests.integration.conftest import create_product, create_user, create_warehouse

ORDER_REFERENCE = "order"

#: Long enough for the second transaction to reach its blocking UPDATE.
LOCK_WAIT_SECONDS = 0.5


async def test_a_reservation_holds_units_without_removing_them(
    db_session: AsyncSession,
) -> None:
    actor = await create_user(db_session)
    warehouse = await create_warehouse(db_session)
    product = await create_product(db_session)
    service = WarehouseService(db_session)
    access = WarehouseAccess(actor_id=actor.id, scope=PermissionScope.ALL)

    await service.receive(
        access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=10),
    )
    level = await service.reserve(
        access,
        ReserveStockRequest(
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity=4,
            reference_type=ORDER_REFERENCE,
            reference_id=uuid.uuid4(),
        ),
    )

    # Reserved units are promised, not shipped: they stay on hand and only stop
    # being available.
    assert level.quantity_on_hand == 10
    assert level.quantity_reserved == 4
    assert level.quantity_available == 6


async def test_every_movement_is_written_to_the_ledger(db_session: AsyncSession) -> None:
    actor = await create_user(db_session)
    warehouse = await create_warehouse(db_session)
    product = await create_product(db_session)
    service = WarehouseService(db_session)
    access = WarehouseAccess(actor_id=actor.id, scope=PermissionScope.ALL)
    reference_id = uuid.uuid4()

    await service.receive(
        access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=10),
    )
    await service.reserve(
        access,
        ReserveStockRequest(
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity=4,
            reference_type=ORDER_REFERENCE,
            reference_id=reference_id,
        ),
    )

    movements = (
        (
            await db_session.execute(
                select(StockMovement)
                .where(StockMovement.product_id == product.id)
                .order_by(StockMovement.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [row.type for row in movements] == [
        StockMovementType.RECEIPT,
        StockMovementType.RESERVATION,
    ]
    # The ledger names what the goods were moved for, so a stock row can always
    # be read back to the order that caused it.
    assert movements[1].reference_type == ORDER_REFERENCE
    assert movements[1].reference_id == reference_id
    assert movements[1].actor_id == actor.id


async def test_reserving_more_than_is_available_is_refused(db_session: AsyncSession) -> None:
    actor = await create_user(db_session)
    warehouse = await create_warehouse(db_session)
    product = await create_product(db_session)
    service = WarehouseService(db_session)
    access = WarehouseAccess(actor_id=actor.id, scope=PermissionScope.ALL)
    await service.receive(
        access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=5),
    )

    with pytest.raises(Exception) as failure:  # noqa: PT011 — the code is the assertion
        await service.reserve(
            access,
            ReserveStockRequest(
                warehouse_id=warehouse.id,
                product_id=product.id,
                quantity=6,
                reference_type=ORDER_REFERENCE,
                reference_id=uuid.uuid4(),
            ),
        )

    assert getattr(failure.value, "code", None) == INSUFFICIENT_STOCK
    # The refusal happens before the write, so the table rule that would also
    # have caught it is never reached.
    level = await db_session.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    assert level is not None
    assert level.quantity_reserved == 0


async def test_releasing_gives_the_promise_back(db_session: AsyncSession) -> None:
    actor = await create_user(db_session)
    warehouse = await create_warehouse(db_session)
    product = await create_product(db_session)
    service = WarehouseService(db_session)
    access = WarehouseAccess(actor_id=actor.id, scope=PermissionScope.ALL)
    reference_id = uuid.uuid4()
    await service.receive(
        access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=10),
    )
    await service.reserve(
        access,
        ReserveStockRequest(
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity=4,
            reference_type=ORDER_REFERENCE,
            reference_id=reference_id,
        ),
    )

    level = await service.release(
        access,
        ReleaseStockRequest(
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity=4,
            reference_type=ORDER_REFERENCE,
            reference_id=reference_id,
        ),
    )

    assert level.quantity_reserved == 0
    assert level.quantity_on_hand == 10

    with pytest.raises(Exception) as failure:  # noqa: PT011 — the code is the assertion
        await service.release(
            access,
            ReleaseStockRequest(
                warehouse_id=warehouse.id,
                product_id=product.id,
                quantity=1,
                reference_type=ORDER_REFERENCE,
                reference_id=reference_id,
            ),
        )
    assert getattr(failure.value, "code", None) == INSUFFICIENT_RESERVATION


async def test_the_version_climbs_with_every_write(db_session: AsyncSession) -> None:
    actor = await create_user(db_session)
    warehouse = await create_warehouse(db_session)
    product = await create_product(db_session)
    service = WarehouseService(db_session)
    access = WarehouseAccess(actor_id=actor.id, scope=PermissionScope.ALL)

    first = await service.receive(
        access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=1),
    )
    second = await service.receive(
        access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=1),
    )

    assert second.version == first.version + 1


@pytest.fixture
async def committed_level(
    engine: AsyncEngine,
) -> tuple[async_sessionmaker[AsyncSession], uuid.UUID, uuid.UUID, uuid.UUID]:
    """A stock level that really exists, reachable from two transactions.

    The savepoint-isolated session cannot express this scenario: two callers
    racing for the same row need two transactions, and a transaction cannot see
    another one's savepoint.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as setup:
        actor = await create_user(setup)
        warehouse = await create_warehouse(setup)
        product = await create_product(setup)
        await WarehouseService(setup).receive(
            WarehouseAccess(actor_id=actor.id, scope=PermissionScope.ALL),
            ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=10),
        )
        await setup.commit()
        # The rows outlive this fixture on purpose: the whole database is a
        # scratch one and is dropped when the session ends.
        return (factory, actor.id, warehouse.id, product.id)


async def test_two_callers_racing_for_the_same_level_do_not_both_win(
    committed_level: tuple[async_sessionmaker[AsyncSession], uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    factory, actor_id, warehouse_id, product_id = committed_level
    access = WarehouseAccess(actor_id=actor_id, scope=PermissionScope.ALL)
    request = ReserveStockRequest(
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity=3,
        reference_type=ORDER_REFERENCE,
        reference_id=uuid.uuid4(),
    )

    async with factory() as first, factory() as second:
        # The winner reads the level and writes it, holding the row lock.
        await WarehouseService(first).reserve(access, request)

        # The loser starts while that write is still uncommitted, so it reads
        # the *old* version and then blocks on the very row it wants to update.
        loser = asyncio.create_task(WarehouseService(second).reserve(access, request))
        await asyncio.sleep(LOCK_WAIT_SECONDS)
        assert not loser.done(), "the second caller was expected to wait on the row lock"

        await first.commit()

        with pytest.raises(Exception) as failure:  # noqa: PT011 — the code is the assertion
            await loser
        await second.rollback()

    # The update matched no row, because the version it named is no longer the
    # one stored — which is exactly the conflict a client is told to retry.
    assert getattr(failure.value, "code", None) == STOCK_CONCURRENT_MODIFICATION
