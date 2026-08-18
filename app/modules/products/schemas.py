"""Wire contract of the catalogue endpoints.

Monetary amounts cross the boundary as strings in both directions. Inbound they
are constrained by a grammar rather than parsed as a number, so ``12.555`` is
rejected instead of being silently rounded; outbound they are rendered by the
shared ``Money`` serializer at a fixed scale.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.core.pagination import ListQuery
from app.core.responses import CamelModel
from app.core.serializers import Money, UtcDatetime
from app.modules.products.types import ProductSortField

MAX_SKU_LENGTH = 64
MAX_NAME_LENGTH = 160
MAX_DESCRIPTION_LENGTH = 4000
MAX_CATEGORY_LENGTH = 80
MAX_SEARCH_LENGTH = 160

#: Up to twelve integer digits and at most two decimals — the range the
#: ``Numeric(14, 2)`` column can hold exactly. A leading sign is not part of the
#: grammar, so a negative amount never reaches the service.
MONEY_PATTERN = r"^\d{1,12}(?:\.\d{1,2})?$"

#: A SKU is folded to upper case on the way in: the catalogue treats ``a-1`` and
#: ``A-1`` as the same article, and the unique index can only see one spelling.
Sku = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        min_length=1,
        max_length=MAX_SKU_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]

CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$"),
]

MoneyAmount = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MONEY_PATTERN)]

ProductName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)
]

ProductDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_DESCRIPTION_LENGTH)
]

ProductCategory = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CATEGORY_LENGTH)
]


class ProductOut(CamelModel):
    """A catalogue entry as the API publishes it."""

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    category: str | None
    unit_price: Money
    currency: str
    is_active: bool
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CreateProductRequest(CamelModel):
    """Body of ``POST /products``."""

    sku: Sku
    name: ProductName
    description: ProductDescription | None = None
    category: ProductCategory | None = None
    unit_price: MoneyAmount
    currency: CurrencyCode = "USD"
    is_active: bool = True


class UpdateProductRequest(CamelModel):
    """Body of ``PATCH /products/{id}``.

    ``sku`` is deliberately absent and the model forbids unknown fields: the
    identifier of a catalogue entry must stay stable for the order lines that
    reference it, so an attempt to change it is refused rather than ignored.
    """

    version: int = Field(ge=1)
    name: ProductName | None = None
    description: ProductDescription | None = None
    category: ProductCategory | None = None
    unit_price: MoneyAmount | None = None
    currency: CurrencyCode | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> UpdateProductRequest:
        # `version` states which record is being edited, not what to change, so
        # a body carrying only a version has nothing to apply.
        if self.model_fields_set <= {"version"}:
            message = "At least one field to update is required"
            raise ValueError(message)
        return self


class ProductListParams(ListQuery):
    """Query string of ``GET /products``.

    Grouped into a model rather than spelled out as nine handler arguments;
    FastAPI reads a model as query parameters just as happily.
    """

    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    category: str | None = Field(default=None, min_length=1, max_length=MAX_CATEGORY_LENGTH)
    is_active: bool | None = None
    min_price: MoneyAmount | None = None
    max_price: MoneyAmount | None = None
    sort_by: ProductSortField = ProductSortField.CREATED_AT

    @model_validator(mode="after")
    def _require_ordered_bounds(self) -> ProductListParams:
        if self.min_price is not None and self.max_price is not None:  # noqa: SIM102
            # Compared as decimals, not as text: "9" is below "10" numerically
            # and above it lexicographically.
            if Decimal(self.min_price) > Decimal(self.max_price):
                message = "minPrice must not exceed maxPrice"
                raise ValueError(message)
        return self
