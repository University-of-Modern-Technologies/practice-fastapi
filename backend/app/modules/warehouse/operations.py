"""The stock port other modules depend on.

Order fulfilment has to reserve, release and issue stock, and each of those has
to succeed or fail together with the order write that caused it. That rules out
a service that opens its own transaction: the two writes would land in two
transactions, and a short stock level would leave a confirmed order behind.

So every operation here runs on the session it is handed. The caller keeps
ownership of the transaction and, once it has committed, calls
``publish_committed`` on the returned change to announce the movement.

The port is described structurally on purpose. Nothing in this file imports the
module that consumes it, and that module imports nothing from here — it declares
the shape it needs and the composition root passes this object in.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.types import DomainEventPublisher, NoopPublisher
from app.modules.warehouse.service import (
    StockChange,
    adjust_plan,
    apply_stock_movements,
    issue_plans,
    receive_plan,
    release_plan,
    reserve_plan,
)
from app.modules.warehouse.types import (
    MovementPlan,
    StockActor,
    StockAdjustmentInput,
    StockOperationInput,
)

__all__ = ["StockOperations", "create_stock_operations"]


class StockOperations:
    """The five movements, each applied on a caller-supplied session."""

    __slots__ = ("_publisher",)

    def __init__(self, publisher: DomainEventPublisher | None = None) -> None:
        self._publisher: DomainEventPublisher = (
            publisher if publisher is not None else NoopPublisher()
        )

    async def receive(
        self, session: AsyncSession, access: StockActor, data: StockOperationInput
    ) -> StockChange:
        return await self._apply(session, access, [receive_plan(data)])

    async def issue(
        self, session: AsyncSession, access: StockActor, data: StockOperationInput
    ) -> StockChange:
        return await self._apply(session, access, issue_plans(data))

    async def reserve(
        self, session: AsyncSession, access: StockActor, data: StockOperationInput
    ) -> StockChange:
        return await self._apply(session, access, [reserve_plan(data)])

    async def release(
        self, session: AsyncSession, access: StockActor, data: StockOperationInput
    ) -> StockChange:
        return await self._apply(session, access, [release_plan(data)])

    async def adjust(
        self, session: AsyncSession, access: StockActor, data: StockAdjustmentInput
    ) -> StockChange:
        return await self._apply(session, access, [adjust_plan(data)])

    async def _apply(
        self, session: AsyncSession, access: StockActor, plans: list[MovementPlan]
    ) -> StockChange:
        return await apply_stock_movements(session, self._publisher, access, plans)


def create_stock_operations(publisher: DomainEventPublisher | None = None) -> StockOperations:
    """Builds the port; it holds no session and no database handle of its own."""
    return StockOperations(publisher)
