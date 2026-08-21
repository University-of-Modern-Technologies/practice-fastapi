"""Wire contract of the order endpoints.

Three fields are conspicuously absent from every request body: ``orderNumber``,
``status`` and the totals. The first two are allocated by the server, and the
totals are derived from the lines — a field that is never declared cannot be
forged by a client, so the guarantee costs nothing to enforce.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.core.pagination import ListQuery
from app.core.responses import CamelModel
from app.core.serializers import Money, UtcDatetime
from app.db.enums import OrderStatus
from app.modules.orders.money import MAX_ITEM_QUANTITY, MONEY_STRING_PATTERN
from app.modules.orders.types import OrderSortField

MAX_NOTES_LENGTH = 4000
MAX_ITEMS_PER_ORDER = 200

#: Amounts travel as strings so no value passes through a client-side float.
MoneyString = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MONEY_STRING_PATTERN)]

#: ISO 4217 alphabetic code, folded to upper case on the way in.
CurrencyCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$")
]

Quantity = Annotated[int, Field(ge=1, le=MAX_ITEM_QUANTITY)]
Version = Annotated[int, Field(ge=1)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_NOTES_LENGTH)]


class OrderItemOut(CamelModel):
    """One line of an order, as it was priced when it was added."""

    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    quantity: int
    unit_price: Money
    line_total: Money
    created_at: UtcDatetime
    updated_at: UtcDatetime


class OrderOut(CamelModel):
    """A sales order with its lines."""

    id: uuid.UUID
    order_number: str
    owner_id: uuid.UUID
    contact_id: uuid.UUID | None
    deal_id: uuid.UUID | None
    status: OrderStatus
    currency: str
    subtotal: Money
    discount_total: Money
    tax_total: Money
    total: Money
    notes: str | None
    version: int
    placed_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    items: list[OrderItemOut]


class OrderItemRequest(CamelModel):
    """One line as it is asked for: a product and how many of it."""

    product_id: uuid.UUID
    quantity: Quantity


class CreateOrderRequest(CamelModel):
    """Body of ``POST /orders``."""

    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    currency: CurrencyCode | None = None
    discount_total: MoneyString | None = None
    tax_total: MoneyString | None = None
    notes: Notes | None = None
    items: list[OrderItemRequest] | None = Field(default=None, max_length=MAX_ITEMS_PER_ORDER)

    @model_validator(mode="after")
    def _reject_repeated_products(self) -> CreateOrderRequest:
        if self.items is not None:
            product_ids = [item.product_id for item in self.items]
            if len(set(product_ids)) != len(product_ids):
                message = "Each product may appear on an order only once"
                raise ValueError(message)
        return self


class UpdateOrderRequest(CamelModel):
    """Body of ``PATCH /orders/{id}``.

    ``version`` is mandatory and is not a field to update: it is the version the
    client last read, and the write is rejected if the order has moved on since.
    """

    version: Version
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    currency: CurrencyCode | None = None
    discount_total: MoneyString | None = None
    tax_total: MoneyString | None = None
    notes: Notes | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> UpdateOrderRequest:
        if self.model_fields_set <= {"version"}:
            message = "At least one field to update is required"
            raise ValueError(message)
        return self


class AddOrderItemRequest(CamelModel):
    """Body of ``POST /orders/{id}/items``."""

    version: Version
    product_id: uuid.UUID
    quantity: Quantity


class UpdateOrderItemRequest(CamelModel):
    """Body of ``PATCH /orders/{id}/items/{itemId}``.

    Only the quantity is negotiable: the snapshot price stays as it was taken.
    """

    version: Version
    quantity: Quantity


class TransitionOrderRequest(CamelModel):
    """Body of ``POST /orders/{id}/transitions``."""

    version: Version
    status: OrderStatus


class OrderListParams(ListQuery):
    """Query string of ``GET /orders``.

    Grouped into a model rather than spelled out as a dozen handler parameters,
    which also puts the cross-field rule (``minTotal ≤ maxTotal``) next to the
    fields it constrains.
    """

    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    status: OrderStatus | None = None
    min_total: MoneyString | None = None
    max_total: MoneyString | None = None
    sort_by: OrderSortField = "createdAt"

    @model_validator(mode="after")
    def _check_total_range(self) -> OrderListParams:
        if (
            self.min_total is not None
            and self.max_total is not None
            and Decimal(self.min_total) > Decimal(self.max_total)
        ):
            message = "minTotal must not exceed maxTotal"
            raise ValueError(message)
        return self
