"""Vocabulary of the warehouse module.

Two things live here that the rest of the module builds on: the machine codes
every failure is reported with, and the *structural* description of what a stock
operation needs from its caller.

The protocols are deliberate. Another module — order fulfilment, for instance —
has to reserve and release stock inside its own transaction, and it must be able
to do so without importing anything from here, just as nothing here imports it.
Describing the caller's data by its shape instead of by its class is what keeps
that dependency pointing in one direction only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.core.errors import ConflictError, VersionConflictError
from app.db.enums import PermissionScope, StockMovementType

__all__ = [
    "INSUFFICIENT_RESERVATION",
    "INSUFFICIENT_STOCK",
    "INVALID_STOCK_ADJUSTMENT",
    "PRODUCT_NOT_FOUND",
    "STOCK_ADJUSTMENT_NOTE_REQUIRED",
    "STOCK_CONCURRENT_MODIFICATION",
    "STOCK_ENTITY_TYPE",
    "STOCK_LEVEL_NOT_FOUND",
    "WAREHOUSE_CODE_IMMUTABLE",
    "WAREHOUSE_CODE_TAKEN",
    "WAREHOUSE_ENTITY_TYPE",
    "WAREHOUSE_INACTIVE",
    "WAREHOUSE_NOT_FOUND",
    "WAREHOUSE_RESOURCE",
    "InsufficientReservationError",
    "InsufficientStockError",
    "MovementPlan",
    "StockActor",
    "StockAdjustmentInput",
    "StockOperationInput",
    "StockVersionConflictError",
    "WarehouseAccess",
    "WarehouseInactiveError",
]

#: Resource half of the ``warehouse:read`` / ``warehouse:write`` permission keys.
WAREHOUSE_RESOURCE = "warehouse"

#: Entity names used in the audit trail and in published events.
WAREHOUSE_ENTITY_TYPE = "warehouse"
STOCK_ENTITY_TYPE = "stock"

# Machine codes are shared between the service, the router and the tests, so a
# rename cannot silently change what a client is allowed to branch on.
WAREHOUSE_NOT_FOUND = "WAREHOUSE_NOT_FOUND"
WAREHOUSE_INACTIVE = "WAREHOUSE_INACTIVE"
WAREHOUSE_CODE_TAKEN = "WAREHOUSE_CODE_TAKEN"
WAREHOUSE_CODE_IMMUTABLE = "WAREHOUSE_CODE_IMMUTABLE"
STOCK_LEVEL_NOT_FOUND = "STOCK_LEVEL_NOT_FOUND"
PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
INSUFFICIENT_RESERVATION = "INSUFFICIENT_RESERVATION"
STOCK_CONCURRENT_MODIFICATION = "STOCK_CONCURRENT_MODIFICATION"
INVALID_STOCK_ADJUSTMENT = "INVALID_STOCK_ADJUSTMENT"
STOCK_ADJUSTMENT_NOTE_REQUIRED = "STOCK_ADJUSTMENT_NOTE_REQUIRED"


class InsufficientStockError(ConflictError):
    """The operation would leave fewer units on the shelf than zero."""

    def __init__(self) -> None:
        super().__init__("Not enough stock available for this operation", INSUFFICIENT_STOCK)


class InsufficientReservationError(ConflictError):
    """The operation would release more units than were ever reserved."""

    def __init__(self) -> None:
        super().__init__("Not enough reserved stock for this operation", INSUFFICIENT_RESERVATION)


class WarehouseInactiveError(ConflictError):
    """A deactivated warehouse accepts no movements at all."""

    def __init__(self) -> None:
        super().__init__("Warehouse is deactivated", WAREHOUSE_INACTIVE)


class StockVersionConflictError(VersionConflictError):
    """Optimistic locking rejected the write: the level moved on meanwhile.

    It stays a ``VersionConflictError`` so any caller may branch on the type,
    while the machine code is the stock-specific one the client already knows.
    """

    def __init__(self) -> None:
        super().__init__("Stock level was modified by another request; retry the operation")
        self.code = STOCK_CONCURRENT_MODIFICATION


@dataclass(frozen=True, slots=True)
class WarehouseAccess:
    """Who is asking, and how broad their grant is.

    Stock is organisation-wide: there is no owner column to narrow a query by,
    so an ``OWN`` grant currently sees exactly what an ``ALL`` grant sees. The
    breadth is carried anyway, because it is what a future per-warehouse
    ownership rule would hook into.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None


class StockActor(Protocol):
    """The identity a stock operation is performed under.

    Only ``actor_id`` is required; ``ip_address`` is read when the caller
    happens to carry one, so a module with a leaner access object still fits.
    """

    @property
    def actor_id(self) -> uuid.UUID: ...


class StockOperationInput(Protocol):
    """What receive, issue, reserve and release need to know.

    Read-only properties, so an object whose ``reference_type`` is a plain
    ``str`` satisfies a contract asking for ``str | None``. ``note`` and
    ``from_reservation`` are read only when present.
    """

    @property
    def warehouse_id(self) -> uuid.UUID: ...

    @property
    def product_id(self) -> uuid.UUID: ...

    @property
    def quantity(self) -> int: ...

    @property
    def reference_type(self) -> str | None: ...

    @property
    def reference_id(self) -> uuid.UUID | None: ...


class StockAdjustmentInput(Protocol):
    """A signed correction, which has a delta and a reason instead of a quantity."""

    @property
    def warehouse_id(self) -> uuid.UUID: ...

    @property
    def product_id(self) -> uuid.UUID: ...

    @property
    def delta(self) -> int: ...

    @property
    def note(self) -> str: ...

    @property
    def reference_type(self) -> str | None: ...

    @property
    def reference_id(self) -> uuid.UUID | None: ...


@dataclass(frozen=True, slots=True)
class MovementPlan:
    """One stock change, described before anything is read or written.

    The deltas are what the guards reason about, which is why a plan is built
    first and validated against the current level second: nothing is written
    until the outcome is known to be legal.
    """

    movement_type: StockMovementType
    event_type: str
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    #: Always positive; the database rejects a movement of zero or fewer units.
    quantity: int
    on_hand_delta: int
    reserved_delta: int
    reference_type: str | None = None
    reference_id: uuid.UUID | None = None
    note: str | None = None
