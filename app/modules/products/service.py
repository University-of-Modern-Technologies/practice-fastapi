"""Catalogue rules.

Three properties are worth stating up front, because everything else here
follows from them:

* an entry is never physically removed — orders reference it, so deletion only
  hides it from the catalogue;
* a SKU identifies an article, so it is unique and immutable;
* every write carries the version it believed it was editing, and a mismatch is
  reported rather than resolved.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, ConflictError, NotFoundError, VersionConflictError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.core.serializers import quantize_money
from app.db.models.product import Product
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.products.schemas import (
    CreateProductRequest,
    ProductListParams,
    ProductOut,
    UpdateProductRequest,
)
from app.modules.products.types import (
    INVALID_PRODUCT_PRICE,
    PRODUCT_CONCURRENT_MODIFICATION,
    PRODUCT_CREATED,
    PRODUCT_DELETED,
    PRODUCT_ENTITY_TYPE,
    PRODUCT_NOT_FOUND,
    PRODUCT_SKU_TAKEN,
    PRODUCT_UPDATED,
    ProductAccess,
    ProductSortField,
)

#: Wire spelling of a sort field to the column it orders by.
SORT_COLUMNS: dict[ProductSortField, InstrumentedAttribute[Any]] = {
    ProductSortField.CREATED_AT: Product.created_at,
    ProductSortField.UPDATED_AT: Product.updated_at,
    ProductSortField.NAME: Product.name,
    ProductSortField.SKU: Product.sku,
    ProductSortField.UNIT_PRICE: Product.unit_price,
    ProductSortField.CATEGORY: Product.category,
}

LIKE_ESCAPE = "\\"


def to_product_out(product: Product) -> ProductOut:
    return ProductOut(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        category=product.category,
        unit_price=product.unit_price,
        currency=product.currency,
        is_active=product.is_active,
        version=product.version,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def like_pattern(term: str) -> str:
    """Turns a search term into a contains-pattern.

    The wildcards of ``LIKE`` are escaped first: a term containing ``%`` is what
    the caller typed, not an instruction to match everything.
    """
    escaped = (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def list_criteria(query: ProductListParams) -> list[ColumnElement[bool]]:
    """Every ``WHERE`` clause the filters add, including the invisible one."""
    min_price = Decimal(query.min_price) if query.min_price is not None else None
    max_price = Decimal(query.max_price) if query.max_price is not None else None
    return (
        # A deleted entry is outside every filter combination there is.
        FilterBuilder([Product.deleted_at.is_(None)])
        .equals(Product.category, query.category)
        .flag(Product.is_active, query.is_active)
        .search(query.search, [Product.name, Product.sku], escape=True)
        .range(Product.unit_price, min_price, max_price)
        .build()
    )


def parse_price(value: str) -> Decimal:
    """Reads an inbound amount, at the scale the column stores.

    The request grammar already rules out a negative or over-precise amount, so
    reaching the guard means the service was called directly.
    """
    amount = quantize_money(Decimal(value))
    if amount < 0:
        raise AppError("Unit price must be non-negative", 400, INVALID_PRODUCT_PRICE)
    return amount


class _ProductPage(PagedQuery[Product, ProductListParams, ProductOut]):
    """One page of the catalogue.

    No access argument: the catalogue has no owner column, so there is nothing
    a narrower grant could be narrowed to. Whether the caller may read at all
    was already decided by the router.
    """

    def _model(self) -> type[Product]:
        return Product

    def _build_filters(self, params: ProductListParams) -> list[ColumnElement[bool]]:
        return list_criteria(params)

    def _order_by(self, params: ProductListParams) -> tuple[ColumnElement[Any], ...]:
        column = SORT_COLUMNS[params.sort_by]
        primary = column.desc() if params.sort_order == "desc" else column.asc()
        # The id breaks ties: two rows sharing a category or a price would
        # otherwise page unpredictably.
        return (primary, Product.id.asc())

    def _to_dto(self, row: Product) -> ProductOut:
        return to_product_out(row)


class ProductsService:
    """Reads and writes catalogue entries on one session."""

    def __init__(
        self,
        session: AsyncSession,
        publisher: DomainEventPublisher | None = None,
    ) -> None:
        self._session = session
        # The same session the caller is on, so a change and its trail entry
        # commit or roll back together.
        self._audit = AuditService(session)
        self._events: DomainEventPublisher = publisher if publisher is not None else NoopPublisher()

    async def list(self, query: ProductListParams) -> tuple[list[ProductOut], int]:
        """One page of the catalogue."""
        return await _ProductPage(self._session).run(query)

    async def get_by_id(self, product_id: uuid.UUID) -> ProductOut:
        return to_product_out(await self._require_active(product_id))

    async def create(self, access: ProductAccess, data: CreateProductRequest) -> ProductOut:
        unit_price = parse_price(data.unit_price)
        await self._require_sku_available(data.sku)

        product = Product(
            id=uuid.uuid4(),
            sku=data.sku,
            name=data.name,
            description=data.description,
            category=data.category,
            unit_price=unit_price,
            currency=data.currency,
            is_active=data.is_active,
        )
        self._session.add(product)
        await self._flush_unique_sku()

        after = to_product_out(product)
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=PRODUCT_CREATED,
                entity_type=PRODUCT_ENTITY_TYPE,
                entity_id=product.id,
                changes={"after": self._payload(after)},
                ip_address=access.ip_address,
            )
        )
        self._announce(PRODUCT_CREATED, product.id, access, {"after": self._payload(after)})
        return after

    async def update(
        self, access: ProductAccess, product_id: uuid.UUID, data: UpdateProductRequest
    ) -> ProductOut:
        product = await self._require_active(product_id, for_update=True)
        if product.version != data.version:
            raise VersionConflictError(
                "Product was modified by another request", PRODUCT_CONCURRENT_MODIFICATION
            )

        before = to_product_out(product)
        fields = data.model_fields_set

        # An absent field means "leave as is"; a field sent as null means "clear
        # it". Only `model_fields_set` can tell the two apart.
        if "name" in fields and data.name is not None:
            product.name = data.name
        if "description" in fields:
            product.description = data.description
        if "category" in fields:
            product.category = data.category
        if "unit_price" in fields and data.unit_price is not None:
            product.unit_price = parse_price(data.unit_price)
        if "currency" in fields and data.currency is not None:
            product.currency = data.currency
        if "is_active" in fields and data.is_active is not None:
            product.is_active = data.is_active

        product.version += 1
        await self._flush_unique_sku()
        # `updated_at` is stamped by the server on every UPDATE, so the value on
        # the instance is stale the moment the statement leaves. Reading it back
        # here is what keeps the response — and the trail entry built from it —
        # showing the timestamp the row actually carries.
        await self._session.refresh(product)

        after = to_product_out(product)
        changes = {"before": self._payload(before), "after": self._payload(after)}
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=PRODUCT_UPDATED,
                entity_type=PRODUCT_ENTITY_TYPE,
                entity_id=product.id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )
        self._announce(PRODUCT_UPDATED, product.id, access, changes)
        return after

    async def delete(self, access: ProductAccess, product_id: uuid.UUID, version: int) -> None:
        """Hides an entry without erasing it.

        Order lines point at the product they were priced from, so the row has
        to survive; ``deleted_at`` is what keeps it out of the catalogue.
        """
        product = await self._require_active(product_id, for_update=True)
        if product.version != version:
            raise VersionConflictError(
                "Product was modified by another request", PRODUCT_CONCURRENT_MODIFICATION
            )

        before = to_product_out(product)
        product.deleted_at = datetime.now(tz=UTC)
        product.version += 1
        await self._session.flush()

        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=PRODUCT_DELETED,
                entity_type=PRODUCT_ENTITY_TYPE,
                entity_id=product.id,
                changes={
                    "before": self._payload(before),
                    "after": {"deletedAt": product.deleted_at, "version": product.version},
                },
                ip_address=access.ip_address,
            )
        )
        self._announce(PRODUCT_DELETED, product.id, access, {"id": str(product_id)})

    async def _require_active(self, product_id: uuid.UUID, *, for_update: bool = False) -> Product:
        statement = select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
        if for_update:
            # The version check and the write that follows it have to see the
            # same row, so a concurrent editor waits here rather than racing.
            statement = statement.with_for_update()
        product = (await self._session.execute(statement)).scalar_one_or_none()
        if product is None:
            raise NotFoundError("Product not found", PRODUCT_NOT_FOUND)
        return product

    async def _require_sku_available(self, sku: str) -> None:
        # Deleted rows are included on purpose: the unique index covers them, so
        # a SKU freed by a soft delete is still taken as far as the database is
        # concerned, and reporting that as a conflict beats an opaque 500.
        taken = await self._session.scalar(select(Product.id).where(Product.sku == sku))
        if taken is not None:
            raise ConflictError("A product with this SKU already exists", PRODUCT_SKU_TAKEN)

    async def _flush_unique_sku(self) -> None:
        """Surfaces the unique index as the conflict it represents.

        The preceding read cannot settle uniqueness on its own: two concurrent
        creates both see a free SKU, and only the index rejects the second.
        """
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(
                "A product with this SKU already exists", PRODUCT_SKU_TAKEN
            ) from error

    @staticmethod
    def _payload(product: ProductOut) -> dict[str, Any]:
        """JSON-safe snapshot, as both the trail and the event log store it."""
        return product.model_dump(mode="json", by_alias=True)

    def _announce(
        self, event_type: str, product_id: uuid.UUID, access: ProductAccess, payload: Any
    ) -> None:
        """Reports a committed change to the secondary consumers.

        Guarded even though publishers promise not to throw: the change is on
        its way to being committed, and a misbehaving listener must not turn a
        successful write into a failed request.
        """
        with contextlib.suppress(Exception):
            self._events.publish(
                DomainEvent(
                    event_type=event_type,
                    entity_type=PRODUCT_ENTITY_TYPE,
                    entity_id=str(product_id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                )
            )
