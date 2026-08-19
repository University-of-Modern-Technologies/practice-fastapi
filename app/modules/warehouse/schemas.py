"""Wire contract of the warehouse endpoints.

Everything a client may send is bounded here, and everything it receives is
declared here — including ``quantityAvailable``, which is computed rather than
stored so that it can never disagree with the two quantities it is derived from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import Field, computed_field, field_validator, model_validator

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.db.enums import StockMovementType

MIN_CODE_LENGTH = 2
MAX_CODE_LENGTH = 32
MAX_NAME_LENGTH = 120
MAX_NOTE_LENGTH = 255
MAX_REFERENCE_TYPE_LENGTH = 64
MAX_SEARCH_LENGTH = 120

#: A single movement may never be larger than this, in either direction.
MAX_QUANTITY = 1_000_000_000

#: Letters, digits, hyphens and underscores, starting with a letter or a digit.
CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"


class WarehouseOut(CamelModel):
    """A warehouse as the API publishes it."""

    id: uuid.UUID
    code: str
    name: str
    is_active: bool
    created_at: UtcDatetime
    updated_at: UtcDatetime


class StockLevelOut(CamelModel):
    """Current quantities of one product in one warehouse."""

    id: uuid.UUID
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity_on_hand: int
    quantity_reserved: int
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def quantity_available(self) -> int:
        """What the next reservation may actually take.

        Derived on the way out and never stored: a third stored counter would
        be one more thing that can fall out of step with the other two.
        """
        return self.quantity_on_hand - self.quantity_reserved


class StockMovementOut(CamelModel):
    """One entry of the append-only movement ledger."""

    id: uuid.UUID
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    type: StockMovementType
    quantity: int
    reference_type: str | None
    reference_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    note: str | None
    created_at: UtcDatetime


def _normalise_code(value: object) -> object:
    """A code identifies a warehouse in every movement, so its case is fixed."""
    return value.strip().upper() if isinstance(value, str) else value


class CreateWarehouseRequest(CamelModel):
    """Body of ``POST /warehouses``."""

    code: str = Field(min_length=MIN_CODE_LENGTH, max_length=MAX_CODE_LENGTH, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    is_active: bool | None = None

    @field_validator("code", mode="before")
    @classmethod
    def _fold_code(cls, value: object) -> object:
        return _normalise_code(value)


class UpdateWarehouseRequest(CamelModel):
    """Body of ``PATCH /warehouses/{id}``.

    ``code`` is accepted only so that a request repeating the current value
    succeeds; a different value is refused by the service, because the code is
    immutable once movements reference it.
    """

    code: str | None = Field(
        default=None, min_length=MIN_CODE_LENGTH, max_length=MAX_CODE_LENGTH, pattern=CODE_PATTERN
    )
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    is_active: bool | None = None

    @field_validator("code", mode="before")
    @classmethod
    def _fold_code(cls, value: object) -> object:
        return _normalise_code(value)

    @model_validator(mode="after")
    def _require_one_field(self) -> Self:
        if not self.model_fields_set:
            message = "At least one field to update is required"
            raise ValueError(message)
        return self


class StockTargetRequest(CamelModel):
    """The pair every stock operation addresses."""

    warehouse_id: uuid.UUID
    product_id: uuid.UUID


class ReceiveStockRequest(StockTargetRequest):
    """Body of ``POST /stock/receive``."""

    quantity: int = Field(ge=1, le=MAX_QUANTITY)
    reference_type: str | None = Field(
        default=None, min_length=1, max_length=MAX_REFERENCE_TYPE_LENGTH
    )
    reference_id: uuid.UUID | None = None
    note: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_LENGTH)


class IssueStockRequest(ReceiveStockRequest):
    """Body of ``POST /stock/issue``."""

    from_reservation: bool = False

    @model_validator(mode="after")
    def _require_reference_for_reservation(self) -> Self:
        # An issue against a reservation releases units somebody is holding, so
        # the ledger has to name whose reservation was consumed.
        if self.from_reservation and (self.reference_type is None or self.reference_id is None):
            message = "An issue against a reservation must name the reservation reference"
            raise ValueError(message)
        return self


class ReserveStockRequest(StockTargetRequest):
    """Body of ``POST /stock/reserve``.

    A reservation is always held on behalf of something, so unlike a receipt it
    cannot be recorded without a reference.
    """

    quantity: int = Field(ge=1, le=MAX_QUANTITY)
    reference_type: str = Field(min_length=1, max_length=MAX_REFERENCE_TYPE_LENGTH)
    reference_id: uuid.UUID
    note: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_LENGTH)


class ReleaseStockRequest(ReserveStockRequest):
    """Body of ``POST /stock/release`` — the same shape a reservation has."""


class AdjustStockRequest(StockTargetRequest):
    """Body of ``POST /stock/adjust``."""

    delta: int = Field(ge=-MAX_QUANTITY, le=MAX_QUANTITY)
    #: Deliberately not optional: an unexplained correction is not auditable.
    note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)
    reference_type: str | None = Field(
        default=None, min_length=1, max_length=MAX_REFERENCE_TYPE_LENGTH
    )
    reference_id: uuid.UUID | None = None

    @field_validator("delta")
    @classmethod
    def _reject_zero(cls, value: int) -> int:
        if value == 0:
            message = "delta must not be zero"
            raise ValueError(message)
        return value


class WarehouseListParams(CamelModel):
    """Query of ``GET /warehouses``.

    Grouped into a model rather than spelled out as a handful of handler
    arguments; FastAPI reads a model as query parameters just as happily.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    is_active: bool | None = None


class StockListParams(CamelModel):
    """Query of ``GET /stock``."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    warehouse_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    #: Available stock is derived and therefore not indexable; the low-stock
    #: filter works on the stored on-hand quantity.
    low_stock_threshold: int | None = Field(default=None, ge=0)


class MovementListParams(CamelModel):
    """Query of ``GET /movements``."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    warehouse_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    type: StockMovementType | None = None
    reference_type: str | None = Field(
        default=None, min_length=1, max_length=MAX_REFERENCE_TYPE_LENGTH
    )
    reference_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None

    @model_validator(mode="after")
    def _require_ordered_window(self) -> Self:
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            message = "createdFrom must not be later than createdTo"
            raise ValueError(message)
        return self
