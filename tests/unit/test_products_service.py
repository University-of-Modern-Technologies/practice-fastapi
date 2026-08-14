"""Catalogue rules: money on the wire, unique SKUs, versions and soft deletes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, VersionConflictError
from app.db.enums import PermissionScope
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.events.types import DomainEvent
from app.modules.products.schemas import (
    CreateProductRequest,
    ProductListParams,
    UpdateProductRequest,
)
from app.modules.products.service import (
    ProductsService,
    like_pattern,
    list_criteria,
    to_product_out,
)
from app.modules.products.types import ProductAccess

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
ACTOR_ID = uuid.uuid4()
ACCESS = ProductAccess(actor_id=ACTOR_ID, scope=PermissionScope.ALL, ip_address="203.0.113.7")


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class FakeResult:
    def __init__(self, values: list[Any] | None = None) -> None:
        self._values = values or []

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)

    def scalar_one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self) -> None:
        self.execute_queue: list[list[Any]] = []
        self.scalar_queue: list[Any] = []
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.flushes = 0
        self.flush_error: Exception | None = None
        self.refreshed: list[Any] = []

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else [])

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushes += 1
        if self.flush_error is not None:
            error, self.flush_error = self.flush_error, None
            raise error
        # Stands in for the column defaults the database would apply.
        for instance in self.added:
            if isinstance(instance, Product):
                instance.version = instance.version or 1
                instance.created_at = instance.created_at or NOW
                instance.updated_at = instance.updated_at or NOW
            elif isinstance(instance, AuditLog):
                instance.id = instance.id or uuid.uuid4()
                instance.created_at = instance.created_at or NOW

    async def refresh(self, instance: Any) -> None:
        # The real session re-reads the row to pick up the server-side
        # `updated_at`; a scripted one has nothing to re-read.
        self.refreshed.append(instance)

    @property
    def products(self) -> list[Product]:
        return [row for row in self.added if isinstance(row, Product)]

    @property
    def audit_entries(self) -> list[AuditLog]:
        return [row for row in self.added if isinstance(row, AuditLog)]


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class BrokenPublisher:
    def publish(self, event: DomainEvent) -> None:  # noqa: ARG002
        message = "the listener is down"
        raise RuntimeError(message)


def changes_of(entry: AuditLog) -> dict[str, Any]:
    """The recorded change, once it is known to be there."""
    assert entry.changes is not None
    return entry.changes


def make_product(**overrides: Any) -> Product:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "sku": "WIDGET-1",
        "name": "Widget",
        "description": "A widget",
        "category": "hardware",
        "unit_price": Decimal("12.50"),
        "currency": "USD",
        "is_active": True,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }
    values.update(overrides)
    return Product(**values)


def create_request(**overrides: Any) -> CreateProductRequest:
    payload: dict[str, Any] = {"sku": "widget-1", "name": "Widget", "unitPrice": "12.5"}
    payload.update(overrides)
    return CreateProductRequest.model_validate(payload)


def make_service(session: FakeSession, publisher: Any = None) -> ProductsService:
    return ProductsService(cast("AsyncSession", session), publisher)


def test_an_amount_travels_in_shortest_exact_form() -> None:
    payload = to_product_out(make_product(unit_price=Decimal("12.50"))).model_dump(by_alias=True)

    # The padding the column carries is not part of the amount: the sibling
    # backend drops it too, and the two responses have to match byte for byte.
    assert payload["unitPrice"] == "12.5"
    assert (
        to_product_out(make_product(unit_price=Decimal("20.00"))).model_dump(by_alias=True)[
            "unitPrice"
        ]
        == "20"
    )


def test_a_sku_is_folded_before_it_is_stored() -> None:
    assert create_request(sku="  widget-1  ").sku == "WIDGET-1"


@pytest.mark.parametrize("amount", ["12.555", "-1", "1e3", "", "12,50"])
def test_an_amount_outside_the_grammar_is_refused(amount: str) -> None:
    with pytest.raises(ValidationError):
        create_request(unitPrice=amount)


def test_a_patch_carrying_only_a_version_has_nothing_to_apply() -> None:
    with pytest.raises(ValidationError):
        UpdateProductRequest.model_validate({"version": 1})


def test_a_patch_may_not_rename_the_article() -> None:
    # The SKU is what order lines point at, so it is not part of the contract.
    with pytest.raises(ValidationError):
        UpdateProductRequest.model_validate({"version": 1, "sku": "OTHER"})


def test_a_sort_field_outside_the_closed_set_is_refused() -> None:
    # The value ends up in ORDER BY; accepting a free string would hand the
    # caller a piece of the query.
    with pytest.raises(ValidationError):
        ProductListParams.model_validate({"sortBy": "unitPrice; drop table products"})


def test_a_price_range_has_to_be_ordered() -> None:
    with pytest.raises(ValidationError):
        ProductListParams.model_validate({"minPrice": "10", "maxPrice": "9"})

    # Compared numerically, not as text, so "9" is below "10".
    assert ProductListParams.model_validate({"minPrice": "9", "maxPrice": "10"}).min_price == "9"


def test_a_search_term_cannot_smuggle_a_wildcard() -> None:
    assert like_pattern("50% off") == "%50\\% off%"
    assert like_pattern("a_b") == "%a\\_b%"


def test_a_deleted_entry_is_outside_every_filter_combination() -> None:
    criteria = list_criteria(ProductListParams.model_validate({"category": "hardware"}))

    assert "deleted_at IS NULL" in str(criteria[0])
    assert len(criteria) == 2


async def test_a_page_reports_the_total_alongside_its_slice() -> None:
    session = FakeSession()
    session.scalar_queue = [7]
    session.execute_queue = [[make_product()]]
    service = make_service(session)

    items, total = await service.list(ProductListParams.model_validate({"page": 2}))

    assert total == 7
    assert [item.sku for item in items] == ["WIDGET-1"]


async def test_a_missing_or_deleted_entry_is_a_not_found() -> None:
    session = FakeSession()
    service = make_service(session)

    with pytest.raises(NotFoundError) as error:
        await service.get_by_id(uuid.uuid4())

    assert error.value.code == "PRODUCT_NOT_FOUND"


async def test_creating_a_product_with_a_taken_sku_is_a_conflict() -> None:
    session = FakeSession()
    session.scalar_queue = [uuid.uuid4()]  # the SKU is already in use
    service = make_service(session)

    with pytest.raises(ConflictError) as error:
        await service.create(ACCESS, create_request())

    assert error.value.code == "PRODUCT_SKU_TAKEN"
    assert error.value.status_code == 409
    assert session.products == []


async def test_a_sku_lost_in_a_race_is_still_reported_as_a_conflict() -> None:
    session = FakeSession()
    session.scalar_queue = [None]  # the SKU looked free a moment ago
    session.flush_error = IntegrityError("insert", None, Exception("duplicate key"))
    service = make_service(session)

    with pytest.raises(ConflictError) as error:
        await service.create(ACCESS, create_request())

    # Only the unique index can settle uniqueness; the preceding read cannot.
    assert error.value.code == "PRODUCT_SKU_TAKEN"


async def test_creating_a_product_records_the_change_and_announces_it() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    service = make_service(session, publisher)

    created = await service.create(ACCESS, create_request(category="hardware"))

    assert created.sku == "WIDGET-1"
    assert created.version == 1
    entry = session.audit_entries[0]
    assert entry.action == "product.created"
    assert entry.entity_type == "product"
    assert entry.actor_id == ACTOR_ID
    assert entry.ip_address == "203.0.113.7"
    assert changes_of(entry)["after"]["unitPrice"] == "12.5"
    assert [event.event_type for event in publisher.published] == ["product.created"]
    assert publisher.published[0].entity_type == "product"


async def test_a_broken_listener_cannot_fail_a_write_that_succeeded() -> None:
    session = FakeSession()
    service = make_service(session, BrokenPublisher())

    created = await service.create(ACCESS, create_request())

    assert created.sku == "WIDGET-1"


async def test_editing_a_stale_version_is_a_conflict() -> None:
    product = make_product(version=4)
    session = FakeSession()
    session.execute_queue = [[product]]
    service = make_service(session)

    with pytest.raises(VersionConflictError) as error:
        await service.update(ACCESS, product.id, UpdateProductRequest(version=3, name="Renamed"))

    assert error.value.code == "PRODUCT_CONCURRENT_MODIFICATION"
    assert error.value.status_code == 409
    assert product.name == "Widget"
    assert product.version == 4


async def test_an_update_distinguishes_an_absent_field_from_an_explicit_null() -> None:
    product = make_product()
    session = FakeSession()
    session.execute_queue = [[product]]
    service = make_service(session)

    await service.update(
        ACCESS,
        product.id,
        UpdateProductRequest.model_validate({"version": 1, "description": None}),
    )

    # `description` was sent as null, so it is cleared; `category` was not sent
    # at all, so it stays.
    assert product.description is None
    assert product.category == "hardware"
    assert product.version == 2


async def test_an_update_records_both_sides_of_the_change() -> None:
    product = make_product()
    session = FakeSession()
    session.execute_queue = [[product]]
    publisher = RecordingPublisher()
    service = make_service(session, publisher)

    after = await service.update(
        ACCESS, product.id, UpdateProductRequest.model_validate({"version": 1, "unitPrice": "20"})
    )

    assert after.unit_price == Decimal("20.00")
    entry = session.audit_entries[0]
    assert entry.action == "product.updated"
    assert changes_of(entry)["before"]["unitPrice"] == "12.5"
    assert changes_of(entry)["after"]["unitPrice"] == "20"
    assert [event.event_type for event in publisher.published] == ["product.updated"]


async def test_deleting_a_product_hides_it_instead_of_erasing_it() -> None:
    product = make_product(version=2)
    session = FakeSession()
    session.execute_queue = [[product]]
    publisher = RecordingPublisher()
    service = make_service(session, publisher)

    await service.delete(ACCESS, product.id, 2)

    # Order lines point at the row they were priced from, so it has to survive.
    assert product.deleted_at is not None
    assert product.version == 3
    assert session.audit_entries[0].action == "product.deleted"
    assert [event.event_type for event in publisher.published] == ["product.deleted"]


async def test_deleting_a_stale_version_is_a_conflict() -> None:
    product = make_product(version=2)
    session = FakeSession()
    session.execute_queue = [[product]]
    service = make_service(session)

    with pytest.raises(VersionConflictError):
        await service.delete(ACCESS, product.id, 1)

    assert product.deleted_at is None
