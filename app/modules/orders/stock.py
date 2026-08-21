"""The stock port of the orders module.

Declaring the port here — rather than importing the warehouse service — is what
keeps the dependency one-way: orders states what it needs, the warehouse module
implements it, and the composition root decides who provides it. Nothing in this
file imports anything from ``app.modules.warehouse``, and nothing should.

Every operation runs on the session the order service is already using, so a
reservation and the status change that caused it commit or roll back together.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import OrderStatus
from app.modules.orders.state import order_state
from app.modules.orders.types import OrderAccess, OrderStockEffect

# Re-exported for callers that used to import the type from this module; it
# now lives in ``types.py`` so ``state.py`` can describe a status without
# importing the stock module, which would otherwise import the state back.

__all__ = [
    "ORDER_STOCK_REFERENCE_TYPE",
    "NoopStockOperations",
    "OrderStockChange",
    "OrderStockEffect",
    "OrderStockInput",
    "OrderStockOperations",
    "OrderWarehouseResolver",
    "OrdersStockPort",
    "stock_effect_for_transition",
]

#: Every movement an order produces is tagged with this reference type and the
#: order's id, so the stock ledger can be read back to the order that moved the
#: goods.
ORDER_STOCK_REFERENCE_TYPE = "order"


def stock_effect_for_transition(
    from_status: OrderStatus, to_status: OrderStatus
) -> OrderStockEffect | None:
    """The stock consequence of a status change.

    - ``DRAFT → CONFIRMED`` promises the goods, so every line is reserved;
    - ``CONFIRMED → CANCELLED`` and ``PAID → CANCELLED`` give the promise back;
    - ``PAID → FULFILLED`` hands the goods over against that reservation.

    Every other transition leaves stock untouched: a draft that is cancelled
    never reserved anything, and payment moves money rather than goods.
    """
    return order_state(from_status).stock_effect(to_status)


@dataclass(frozen=True, slots=True)
class OrderStockInput:
    """One stock request, describing a single order line against one warehouse."""

    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    reference_type: str
    reference_id: uuid.UUID
    #: Set when the movement consumes a reservation the order already holds.
    from_reservation: bool = False


class OrderStockChange(Protocol):
    """What a stock operation hands back.

    The order service treats it as opaque except for the callback, which it
    invokes once its own work has succeeded, so that stock events keep following
    the after-commit rule.
    """

    def publish_committed(self) -> None: ...


class OrderStockOperations(Protocol):
    """The stock operations an order needs, each on the caller's session."""

    async def reserve(
        self, session: AsyncSession, access: OrderAccess, data: OrderStockInput
    ) -> OrderStockChange: ...

    async def release(
        self, session: AsyncSession, access: OrderAccess, data: OrderStockInput
    ) -> OrderStockChange: ...

    async def issue(
        self, session: AsyncSession, access: OrderAccess, data: OrderStockInput
    ) -> OrderStockChange: ...


#: Resolves the warehouse an order draws on. An order carries no warehouse of
#: its own, so the choice is a deployment decision: the callback runs on the
#: order's session and returns the target warehouse id, or nothing at all when
#: none is configured.
OrderWarehouseResolver = Callable[[AsyncSession], Awaitable[uuid.UUID | None]]


class _NoopStockChange:
    """A change nobody has to hear about."""

    def publish_committed(self) -> None:
        """Intentionally empty: there was no movement to announce."""


class NoopStockOperations:
    """Default implementation for a composition assembled without a warehouse.

    It exists so the orders module builds, and its unit tests run, without the
    warehouse module being present at all — the transition then moves the order
    and nothing else, exactly as it did before stock existed.
    """

    # The parameters are the port's, not this implementation's: they are named
    # so the signature matches, and ignored because there is nothing to move.
    async def reserve(
        self,
        session: AsyncSession,  # noqa: ARG002
        access: OrderAccess,  # noqa: ARG002
        data: OrderStockInput,  # noqa: ARG002
    ) -> OrderStockChange:
        return _NoopStockChange()

    async def release(
        self,
        session: AsyncSession,  # noqa: ARG002
        access: OrderAccess,  # noqa: ARG002
        data: OrderStockInput,  # noqa: ARG002
    ) -> OrderStockChange:
        return _NoopStockChange()

    async def issue(
        self,
        session: AsyncSession,  # noqa: ARG002
        access: OrderAccess,  # noqa: ARG002
        data: OrderStockInput,  # noqa: ARG002
    ) -> OrderStockChange:
        return _NoopStockChange()


async def _no_warehouse(session: AsyncSession) -> uuid.UUID | None:  # noqa: ARG001
    """Resolver for a deployment that holds no stock at all."""
    return None


@dataclass(frozen=True, slots=True)
class OrdersStockPort:
    """Everything the orders service needs to move stock, injected as one unit."""

    operations: OrderStockOperations
    resolve_warehouse_id: OrderWarehouseResolver = _no_warehouse
