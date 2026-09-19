"""Loads the demonstration data set.

This is deliberately *not* the canonical seed. The canonical set is small,
hand-written and load-bearing: the contract scenarios log in as its users and
read its rows, so growing it would break them wholesale. This script adds a
second, much larger set on top, in its own identifier range, and the two never
meet.

Nothing here invents data. Every row comes from the committed fixture under
``scripts/demo_data``, which the sibling backend reads as well — one fixture,
two databases, identical rows.

Run with ``python -m scripts.demo_seed``. The canonical seed has to have run
first: roles are looked up by name rather than created here.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.base import Base
from app.db.models import (
    AuditLog,
    Contact,
    Deal,
    Order,
    OrderItem,
    Product,
    Role,
    User,
    UserRole,
    Warehouse,
)
from app.db.models.warehouse import StockLevel, StockMovement
from scripts.seed import read_seed_password

DATA_DIRECTORY = Path(__file__).resolve().parent / "demo_data"

#: asyncpg accepts at most 32767 bound parameters in one statement.
MAX_BIND_PARAMETERS = 30_000

#: One bound parameter per element of an ``IN`` list.
DELETE_CHUNK = 2_000


def read(file_name: str) -> list[dict[str, Any]]:
    """Reads one newline-delimited JSON file from the fixture."""
    text = (DATA_DIRECTORY / file_name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def moment(value: str | None) -> datetime | None:
    """Parses an ISO-8601 instant; the fixture writes nothing else."""
    return None if value is None else datetime.fromisoformat(value)


def day(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def table_of(model: type[Base]) -> Table:
    """Narrows a model's mapped table to the concrete ``Table`` type."""
    return cast(Table, model.__table__)


def chunked(rows: Sequence[Mapping[str, Any]], columns: int) -> Iterator[Sequence[Any]]:
    """Splits an insert into statements the driver will accept."""
    size = max(1, MAX_BIND_PARAMETERS // max(columns, 1))
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def insert_all(
    connection: AsyncConnection, model: type[Base], rows: Sequence[Mapping[str, Any]]
) -> None:
    if not rows:
        return
    table = table_of(model)
    for batch in chunked(rows, len(rows[0])):
        await connection.execute(table.insert().values(list(batch)))


async def clear_previous_run(
    connection: AsyncConnection, identifiers: Mapping[str, Sequence[uuid.UUID]]
) -> None:
    """Removes exactly the rows a previous run wrote, and nothing else.

    An earlier version deleted by identifier range instead, which reads as the
    tidier idea and is wrong: rows the canonical seed leaves to the database to
    identify — stock levels, and every audit entry the running application
    writes — get a random UUID, and one in sixteen of those lands inside the
    demonstration range. Measured, not theorised: a second run of the range
    version destroyed a canonical stock level.

    A row the application created against a demonstration record will block the
    delete through a foreign key. That is the intended outcome: refusing to
    reload is better than quietly removing somebody's work.
    """
    ordered: tuple[tuple[str, type[Base]], ...] = (
        ("audit-logs", AuditLog),
        ("stock-movements", StockMovement),
        ("stock-levels", StockLevel),
        ("order-items", OrderItem),
        ("orders", Order),
        ("warehouses", Warehouse),
        ("products", Product),
        ("deals", Deal),
        ("contacts", Contact),
    )
    for name, model in ordered:
        table = table_of(model)
        values = identifiers.get(name, ())
        for start in range(0, len(values), DELETE_CHUNK):
            batch = values[start : start + DELETE_CHUNK]
            await connection.execute(table.delete().where(table.c.id.in_(batch)))

    user_ids = identifiers.get("users", ())
    user_roles = table_of(UserRole)
    users = table_of(User)
    for start in range(0, len(user_ids), DELETE_CHUNK):
        batch = user_ids[start : start + DELETE_CHUNK]
        await connection.execute(user_roles.delete().where(user_roles.c.user_id.in_(batch)))
        await connection.execute(users.delete().where(users.c.id.in_(batch)))


def user_rows(
    fixture: Sequence[Mapping[str, Any]], password_hash: str
) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "email": row["email"],
            "name": row["name"],
            "password_hash": password_hash,
            "is_active": row["isActive"],
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
        }
        for row in fixture
    ]


def contact_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "owner_id": uuid.UUID(row["ownerId"]),
            "first_name": row["firstName"],
            "last_name": row["lastName"],
            "email": row["email"],
            "phone": row["phone"],
            "company": row["company"],
            "notes": row["notes"],
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
            "deleted_at": moment(row["deletedAt"]),
        }
        for row in fixture
    ]


def deal_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "owner_id": uuid.UUID(row["ownerId"]),
            "contact_id": None if row["contactId"] is None else uuid.UUID(row["contactId"]),
            "title": row["title"],
            "stage": row["stage"],
            "amount": Decimal(row["amount"]),
            "currency": row["currency"],
            "probability": row["probability"],
            "version": row["version"],
            "expected_close_date": day(row["expectedCloseDate"]),
            "closed_at": moment(row["closedAt"]),
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
            "deleted_at": moment(row["deletedAt"]),
        }
        for row in fixture
    ]


def product_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "sku": row["sku"],
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "unit_price": Decimal(row["unitPrice"]),
            "currency": row["currency"],
            "is_active": row["isActive"],
            "version": row["version"],
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
            "deleted_at": moment(row["deletedAt"]),
        }
        for row in fixture
    ]


def warehouse_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "code": row["code"],
            "name": row["name"],
            "is_active": row["isActive"],
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
        }
        for row in fixture
    ]


def order_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "order_number": row["orderNumber"],
            "owner_id": uuid.UUID(row["ownerId"]),
            "contact_id": None if row["contactId"] is None else uuid.UUID(row["contactId"]),
            "deal_id": None if row["dealId"] is None else uuid.UUID(row["dealId"]),
            "status": row["status"],
            "currency": row["currency"],
            "subtotal": Decimal(row["subtotal"]),
            "discount_total": Decimal(row["discountTotal"]),
            "tax_total": Decimal(row["taxTotal"]),
            "total": Decimal(row["total"]),
            "notes": row["notes"],
            "version": row["version"],
            "placed_at": moment(row["placedAt"]),
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
            "deleted_at": moment(row["deletedAt"]),
        }
        for row in fixture
    ]


def order_item_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "order_id": uuid.UUID(row["orderId"]),
            "product_id": uuid.UUID(row["productId"]),
            "sku": row["sku"],
            "name": row["name"],
            "quantity": row["quantity"],
            "unit_price": Decimal(row["unitPrice"]),
            "line_total": Decimal(row["lineTotal"]),
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
        }
        for row in fixture
    ]


def stock_level_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "warehouse_id": uuid.UUID(row["warehouseId"]),
            "product_id": uuid.UUID(row["productId"]),
            "quantity_on_hand": row["quantityOnHand"],
            "quantity_reserved": row["quantityReserved"],
            "version": row["version"],
            "created_at": moment(row["createdAt"]),
            "updated_at": moment(row["updatedAt"]),
        }
        for row in fixture
    ]


def stock_movement_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.UUID(row["id"]),
            "warehouse_id": uuid.UUID(row["warehouseId"]),
            "product_id": uuid.UUID(row["productId"]),
            "type": row["type"],
            "quantity": row["quantity"],
            "reference_type": row["referenceType"],
            "reference_id": None if row["referenceId"] is None else uuid.UUID(row["referenceId"]),
            "actor_id": None if row["actorId"] is None else uuid.UUID(row["actorId"]),
            "note": row["note"],
            "created_at": moment(row["createdAt"]),
        }
        for row in fixture
    ]


def audit_rows(fixture: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    # The model attribute is ``meta`` because ``metadata`` is taken by the
    # declarative base, but this is a Core insert against the table, and there
    # the column is still named ``metadata``.
    return [
        {
            "id": uuid.UUID(row["id"]),
            "actor_id": None if row["actorId"] is None else uuid.UUID(row["actorId"]),
            "action": row["action"],
            "entity_type": row["entityType"],
            "entity_id": None if row["entityId"] is None else uuid.UUID(row["entityId"]),
            "changes": row["changes"],
            "metadata": row["metadata"],
            "ip_address": row["ipAddress"],
            "created_at": moment(row["createdAt"]),
        }
        for row in fixture
    ]


async def load(connection: AsyncConnection, password_hash: str) -> dict[str, int]:
    users = read("users.ndjson")

    # The order is the order of the foreign keys; nothing here is negotiable.
    stages: tuple[tuple[str, type[Base], Callable[..., list[dict[str, Any]]]], ...] = (
        ("contacts", Contact, contact_rows),
        ("deals", Deal, deal_rows),
        ("products", Product, product_rows),
        ("warehouses", Warehouse, warehouse_rows),
        ("orders", Order, order_rows),
        ("order-items", OrderItem, order_item_rows),
        ("stock-levels", StockLevel, stock_level_rows),
        ("stock-movements", StockMovement, stock_movement_rows),
        ("audit-logs", AuditLog, audit_rows),
    )
    fixtures = {name: read(f"{name}.ndjson") for name, _, _ in stages}

    roles = await connection.execute(select(table_of(Role).c.name, table_of(Role).c.id))
    role_ids = {str(name): value for name, value in roles.all()}
    for row in users:
        if row["role"] not in role_ids:
            message = (
                f"Role {row['role']!r} is missing. "
                "Run the canonical seed (python -m scripts.seed) first."
            )
            raise RuntimeError(message)

    identifiers: dict[str, Sequence[uuid.UUID]] = {
        name: [uuid.UUID(row["id"]) for row in rows] for name, rows in fixtures.items()
    }
    identifiers["users"] = [uuid.UUID(row["id"]) for row in users]
    await clear_previous_run(connection, identifiers)

    await insert_all(connection, User, user_rows(users, password_hash))
    await insert_all(
        connection,
        UserRole,
        [{"user_id": uuid.UUID(row["id"]), "role_id": role_ids[row["role"]]} for row in users],
    )

    counts = {"users": len(users)}
    for name, model, builder in stages:
        fixture = fixtures[name]
        await insert_all(connection, model, builder(fixture))
        counts[name] = len(fixture)
    return counts


async def demo_seed() -> None:
    password_hash = hash_password(read_seed_password())
    engine = create_async_engine(get_settings().database_url)

    try:
        # One transaction: a half-loaded demonstration set is worse than none.
        async with engine.begin() as connection:
            counts = await load(connection, password_hash)
    finally:
        await engine.dispose()

    print("Demonstration data loaded:")
    for name, count in counts.items():
        print(f"  {name:<16} {count}")


if __name__ == "__main__":
    asyncio.run(demo_seed())
