"""Idempotent development seed.

Every write is an upsert keyed on a natural identifier, so running the script a
second time refreshes the demo data instead of duplicating it. Identifiers of
the demo records are fixed constants for the same reason: a rerun has to land on
the rows it wrote last time.

Run with ``python -m scripts.seed``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.base import Base
from app.db.enums import DealStage, OrderStatus, PermissionScope
from app.db.models import (
    Contact,
    Deal,
    Order,
    OrderItem,
    OrganizationSetting,
    Permission,
    Product,
    Role,
    RolePermission,
    User,
    UserRole,
    Warehouse,
)
from app.db.models.warehouse import StockLevel

MIN_PASSWORD_LENGTH = 12
PLACEHOLDER_PASSWORD = "change-me"

USER_IDS = {
    "admin": uuid.UUID("10000000-0000-4000-8000-000000000001"),
    "manager": uuid.UUID("10000000-0000-4000-8000-000000000002"),
    "viewer": uuid.UUID("10000000-0000-4000-8000-000000000003"),
}
CONTACT_IDS = {
    "northwind": uuid.UUID("20000000-0000-4000-8000-000000000001"),
    "blue_peak": uuid.UUID("20000000-0000-4000-8000-000000000002"),
    "cedar_labs": uuid.UUID("20000000-0000-4000-8000-000000000003"),
}
DEAL_IDS = {
    "onboarding": uuid.UUID("30000000-0000-4000-8000-000000000001"),
    "renewal": uuid.UUID("30000000-0000-4000-8000-000000000002"),
    "pilot": uuid.UUID("30000000-0000-4000-8000-000000000003"),
}
PRODUCT_IDS = {
    "licence": uuid.UUID("40000000-0000-4000-8000-000000000001"),
    "workshop": uuid.UUID("40000000-0000-4000-8000-000000000002"),
    "support": uuid.UUID("40000000-0000-4000-8000-000000000003"),
    # Neither carries real business meaning — they exist so a change that
    # reads "may this product be archived" has one case that says yes
    # without any preparation and one closed-order-only case to read.
    "unblocked": uuid.UUID("40000000-0000-4000-8000-000000000004"),
    "closed_order_only": uuid.UUID("40000000-0000-4000-8000-000000000005"),
}
WAREHOUSE_IDS = {
    "central": uuid.UUID("50000000-0000-4000-8000-000000000001"),
    "regional": uuid.UUID("50000000-0000-4000-8000-000000000002"),
}
ORDER_IDS = {
    "confirmed": uuid.UUID("60000000-0000-4000-8000-000000000001"),
    "draft": uuid.UUID("60000000-0000-4000-8000-000000000002"),
    "fulfilled": uuid.UUID("60000000-0000-4000-8000-000000000003"),
}
ORDER_ITEM_IDS = {
    "confirmed_licence": uuid.UUID("70000000-0000-4000-8000-000000000001"),
    "confirmed_support": uuid.UUID("70000000-0000-4000-8000-000000000002"),
    "draft_workshop": uuid.UUID("70000000-0000-4000-8000-000000000003"),
    "fulfilled_closed_order_only": uuid.UUID("70000000-0000-4000-8000-000000000004"),
}

PERMISSIONS: Sequence[tuple[str, str]] = (
    ("users:read", "View users"),
    ("users:create", "Create users"),
    ("users:update", "Update users"),
    ("users:disable", "Disable users"),
    ("contacts:read", "View contacts"),
    ("contacts:write", "Create and update contacts"),
    ("contacts:delete", "Soft-delete contacts"),
    ("deals:read", "View deals"),
    ("deals:write", "Create and update deals"),
    ("deals:delete", "Soft-delete deals"),
    ("audit:read", "View audit history"),
    ("products:read", "View the product catalogue"),
    ("products:write", "Create and update products"),
    ("products:delete", "Soft-delete products"),
    ("orders:read", "View orders"),
    ("orders:write", "Create and update orders"),
    ("orders:delete", "Soft-delete orders"),
    ("warehouse:read", "View stock levels and movements"),
    ("warehouse:write", "Receive, issue and adjust stock"),
    ("settings:read", "View organization settings"),
    ("settings:write", "Change organization settings"),
    ("analytics:read", "View reports and aggregations"),
    ("integrations:read", "View integration status"),
    ("integrations:write", "Trigger integration operations"),
    ("ai:use", "Use the AI assistance features"),
)

ROLES: Sequence[tuple[str, str]] = (
    ("admin", "Full application administration"),
    ("manager", "CRM team management"),
    ("viewer", "Read-only access to owned CRM records"),
)

MANAGER_GRANTS: Sequence[tuple[str, PermissionScope]] = tuple(
    (key, PermissionScope.ALL)
    for key in (
        "users:read",
        "contacts:read",
        "contacts:write",
        "contacts:delete",
        "deals:read",
        "deals:write",
        "deals:delete",
        "audit:read",
        "products:read",
        "products:write",
        "orders:read",
        "orders:write",
        "orders:delete",
        "warehouse:read",
        "warehouse:write",
        "settings:read",
        "analytics:read",
        "integrations:read",
        "ai:use",
    )
)

VIEWER_GRANTS: Sequence[tuple[str, PermissionScope]] = (
    ("contacts:read", PermissionScope.OWN),
    ("deals:read", PermissionScope.OWN),
    ("products:read", PermissionScope.ALL),
    ("orders:read", PermissionScope.OWN),
    ("warehouse:read", PermissionScope.ALL),
)

GRANTS: Mapping[str, Sequence[tuple[str, PermissionScope]]] = {
    # The administrator holds every permission at the widest scope; the other
    # two roles are the interesting ones to reason about in a lesson.
    "admin": tuple((key, PermissionScope.ALL) for key, _ in PERMISSIONS),
    "manager": MANAGER_GRANTS,
    "viewer": VIEWER_GRANTS,
}


def read_seed_password() -> str:
    """Reads and validates the demo password from the configuration."""
    settings = get_settings()
    if settings.is_production:
        message = "The training seed is local-only and cannot run in production."
        raise RuntimeError(message)

    password = settings.seed_user_password or ""
    if len(password) < MIN_PASSWORD_LENGTH or password == PLACEHOLDER_PASSWORD:
        message = "SEED_USER_PASSWORD must contain at least 12 non-placeholder characters."
        raise RuntimeError(message)

    return password


def table_of(model: type[Base]) -> Table:
    """Narrows a model's mapped table to the concrete `Table` type.

    The declarative base annotates ``__table__`` as the looser ``FromClause``,
    which does not expose the column collection the upsert helpers rely on.
    """
    return cast(Table, model.__table__)


async def upsert(
    connection: AsyncConnection,
    table: Table,
    rows: Sequence[Mapping[str, Any]],
    *,
    conflict: Sequence[str],
    update: Sequence[str],
) -> None:
    """Inserts rows, refreshing the named columns when the key already exists."""
    if not rows:
        return

    statement = insert(table).values(list(rows))
    assignments: dict[str, Any] = {name: statement.excluded[name] for name in update}
    if "updated_at" in table.columns:
        # The ORM-level ``onupdate`` does not apply to a Core upsert, so the
        # timestamp is refreshed explicitly.
        assignments["updated_at"] = func.now()

    if assignments:
        statement = statement.on_conflict_do_update(index_elements=conflict, set_=assignments)
    else:
        statement = statement.on_conflict_do_nothing(index_elements=conflict)

    await connection.execute(statement)


async def id_map(
    connection: AsyncConnection, table: Table, key_column: str
) -> dict[str, uuid.UUID]:
    """Natural key to primary key, so dependants never guess an identifier."""
    result = await connection.execute(select(table.c[key_column], table.c.id))
    return {str(key): value for key, value in result.all()}


async def seed_rbac(connection: AsyncConnection) -> tuple[dict[str, uuid.UUID], ...]:
    await upsert(
        connection,
        table_of(Role),
        [{"id": uuid.uuid4(), "name": name, "description": text} for name, text in ROLES],
        conflict=["name"],
        update=["description"],
    )
    await upsert(
        connection,
        table_of(Permission),
        [{"id": uuid.uuid4(), "key": key, "description": text} for key, text in PERMISSIONS],
        conflict=["key"],
        update=["description"],
    )

    roles = await id_map(connection, table_of(Role), "name")
    permissions = await id_map(connection, table_of(Permission), "key")

    await upsert(
        connection,
        table_of(RolePermission),
        [
            {
                "role_id": roles[role_name],
                "permission_id": permissions[permission_key],
                "scope": scope,
            }
            for role_name, role_grants in GRANTS.items()
            for permission_key, scope in role_grants
        ],
        conflict=["role_id", "permission_id"],
        update=["scope"],
    )

    return roles, permissions


async def seed_users(
    connection: AsyncConnection, roles: Mapping[str, uuid.UUID], password_hash: str
) -> None:
    accounts = (
        (USER_IDS["admin"], "admin@crm-training.example", "Avery Admin", "admin"),
        (USER_IDS["manager"], "manager@crm-training.example", "Morgan Manager", "manager"),
        (USER_IDS["viewer"], "viewer@crm-training.example", "Taylor Viewer", "viewer"),
    )

    await upsert(
        connection,
        table_of(User),
        [
            {
                "id": user_id,
                "email": email,
                "name": name,
                "password_hash": password_hash,
                "is_active": True,
            }
            for user_id, email, name, _ in accounts
        ],
        conflict=["email"],
        update=["name", "password_hash", "is_active"],
    )

    users = await id_map(connection, table_of(User), "email")

    await upsert(
        connection,
        table_of(UserRole),
        [
            {"user_id": users[email], "role_id": roles[role_name]}
            for _, email, _, role_name in accounts
        ],
        conflict=["user_id", "role_id"],
        update=[],
    )


async def seed_crm(connection: AsyncConnection) -> None:
    contacts = (
        (
            CONTACT_IDS["northwind"],
            USER_IDS["manager"],
            "Alex",
            "North",
            "alex.north@example.test",
            "+1-555-0101",
            "Northwind Workshop",
            "Synthetic training contact.",
        ),
        (
            CONTACT_IDS["blue_peak"],
            USER_IDS["manager"],
            "Jordan",
            "Blue",
            "jordan.blue@example.test",
            "+1-555-0102",
            "Blue Peak Studio",
            "Synthetic training contact.",
        ),
        (
            CONTACT_IDS["cedar_labs"],
            USER_IDS["viewer"],
            "Casey",
            "Cedar",
            "casey.cedar@example.test",
            "+1-555-0103",
            "Cedar Labs",
            "Synthetic training contact owned by the viewer.",
        ),
    )

    await upsert(
        connection,
        table_of(Contact),
        [
            {
                "id": contact_id,
                "owner_id": owner_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "company": company,
                "notes": notes,
                "deleted_at": None,
            }
            for (
                contact_id,
                owner_id,
                first_name,
                last_name,
                email,
                phone,
                company,
                notes,
            ) in contacts
        ],
        conflict=["id"],
        update=[
            "owner_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "company",
            "notes",
            "deleted_at",
        ],
    )

    deals = (
        (
            DEAL_IDS["onboarding"],
            USER_IDS["manager"],
            CONTACT_IDS["northwind"],
            "Team onboarding package",
            DealStage.QUALIFIED,
            Decimal("4800.00"),
            25,
        ),
        (
            DEAL_IDS["renewal"],
            USER_IDS["manager"],
            CONTACT_IDS["blue_peak"],
            "Annual service renewal",
            DealStage.PROPOSAL,
            Decimal("12500.00"),
            75,
        ),
        (
            DEAL_IDS["pilot"],
            USER_IDS["viewer"],
            CONTACT_IDS["cedar_labs"],
            "Training workspace pilot",
            DealStage.LEAD,
            Decimal("2400.00"),
            10,
        ),
    )

    await upsert(
        connection,
        table_of(Deal),
        [
            {
                "id": deal_id,
                "owner_id": owner_id,
                "contact_id": contact_id,
                "title": title,
                "stage": stage,
                "amount": amount,
                "currency": "USD",
                "probability": probability,
                "version": 1,
                "deleted_at": None,
            }
            for deal_id, owner_id, contact_id, title, stage, amount, probability in deals
        ],
        conflict=["id"],
        update=[
            "owner_id",
            "contact_id",
            "title",
            "stage",
            "amount",
            "currency",
            "probability",
            "deleted_at",
        ],
    )


async def seed_catalogue(connection: AsyncConnection) -> None:
    products = (
        (
            PRODUCT_IDS["licence"],
            "LIC-TEAM-01",
            "Team licence, annual",
            "Annual licence for a single team workspace.",
            "Licences",
            Decimal("1200.00"),
        ),
        (
            PRODUCT_IDS["workshop"],
            "SRV-WS-02",
            "Onboarding workshop",
            "Two-day onboarding workshop for a new team.",
            "Services",
            Decimal("2400.00"),
        ),
        (
            PRODUCT_IDS["support"],
            "SUP-PRIO-03",
            "Priority support, annual",
            "Priority response times for one year.",
            "Support",
            Decimal("600.00"),
        ),
        (
            PRODUCT_IDS["unblocked"],
            "LIC-LEGACY-04",
            "Legacy licence, discontinued",
            "Superseded by the team licence; nothing open references it.",
            "Licences",
            Decimal("900.00"),
        ),
        (
            PRODUCT_IDS["closed_order_only"],
            "SRV-PILOT-05",
            "One-time pilot engagement",
            "A single delivered engagement; its only order is fulfilled.",
            "Services",
            Decimal("450.00"),
        ),
    )

    await upsert(
        connection,
        table_of(Product),
        [
            {
                "id": product_id,
                "sku": sku,
                "name": name,
                "description": description,
                "category": category,
                "unit_price": unit_price,
                "currency": "USD",
                "is_active": True,
                "deleted_at": None,
            }
            for product_id, sku, name, description, category, unit_price in products
        ],
        conflict=["sku"],
        update=["name", "description", "category", "unit_price", "is_active", "deleted_at"],
    )

    await upsert(
        connection,
        table_of(Warehouse),
        [
            {"id": WAREHOUSE_IDS["central"], "code": "CENTRAL", "name": "Central warehouse"},
            {"id": WAREHOUSE_IDS["regional"], "code": "REGIONAL", "name": "Regional warehouse"},
        ],
        conflict=["code"],
        update=["name", "is_active"],
    )

    warehouses = await id_map(connection, table_of(Warehouse), "code")
    catalogue = await id_map(connection, table_of(Product), "sku")

    await upsert(
        connection,
        table_of(StockLevel),
        [
            {
                "id": uuid.uuid4(),
                "warehouse_id": warehouses[code],
                "product_id": catalogue[sku],
                "quantity_on_hand": on_hand,
                "quantity_reserved": reserved,
                "version": 1,
            }
            for code, sku, on_hand, reserved in (
                ("CENTRAL", "LIC-TEAM-01", 120, 10),
                ("CENTRAL", "SUP-PRIO-03", 80, 0),
                ("REGIONAL", "SRV-WS-02", 15, 3),
                ("CENTRAL", "LIC-LEGACY-04", 6, 0),
                ("CENTRAL", "SRV-PILOT-05", 4, 0),
            )
        ],
        conflict=["warehouse_id", "product_id"],
        update=["quantity_on_hand", "quantity_reserved"],
    )


async def seed_orders(connection: AsyncConnection) -> None:
    await upsert(
        connection,
        table_of(Order),
        [
            {
                "id": ORDER_IDS["confirmed"],
                "order_number": "ORD-2026-0001",
                "owner_id": USER_IDS["manager"],
                "contact_id": CONTACT_IDS["northwind"],
                "deal_id": DEAL_IDS["onboarding"],
                "status": OrderStatus.CONFIRMED,
                "currency": "USD",
                "subtotal": Decimal("1800.00"),
                "discount_total": Decimal("0.00"),
                "tax_total": Decimal("0.00"),
                "total": Decimal("1800.00"),
                "version": 1,
                "placed_at": datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
                "deleted_at": None,
            },
            {
                "id": ORDER_IDS["draft"],
                "order_number": "ORD-2026-0002",
                "owner_id": USER_IDS["viewer"],
                "contact_id": CONTACT_IDS["cedar_labs"],
                "deal_id": None,
                "status": OrderStatus.DRAFT,
                "currency": "USD",
                "subtotal": Decimal("2400.00"),
                "discount_total": Decimal("0.00"),
                "tax_total": Decimal("0.00"),
                "total": Decimal("2400.00"),
                "version": 1,
                "placed_at": None,
                "deleted_at": None,
            },
            {
                "id": ORDER_IDS["fulfilled"],
                "order_number": "ORD-2026-0003",
                "owner_id": USER_IDS["manager"],
                "contact_id": CONTACT_IDS["blue_peak"],
                "deal_id": None,
                "status": OrderStatus.FULFILLED,
                "currency": "USD",
                "subtotal": Decimal("450.00"),
                "discount_total": Decimal("0.00"),
                "tax_total": Decimal("0.00"),
                "total": Decimal("450.00"),
                "version": 1,
                "placed_at": datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
                "deleted_at": None,
            },
        ],
        conflict=["order_number"],
        update=[
            "owner_id",
            "contact_id",
            "deal_id",
            "status",
            "currency",
            "subtotal",
            "discount_total",
            "tax_total",
            "total",
            "placed_at",
            "deleted_at",
        ],
    )

    await upsert(
        connection,
        table_of(OrderItem),
        [
            {
                "id": ORDER_ITEM_IDS["confirmed_licence"],
                "order_id": ORDER_IDS["confirmed"],
                "product_id": PRODUCT_IDS["licence"],
                "sku": "LIC-TEAM-01",
                "name": "Team licence, annual",
                "quantity": 1,
                "unit_price": Decimal("1200.00"),
                "line_total": Decimal("1200.00"),
            },
            {
                "id": ORDER_ITEM_IDS["confirmed_support"],
                "order_id": ORDER_IDS["confirmed"],
                "product_id": PRODUCT_IDS["support"],
                "sku": "SUP-PRIO-03",
                "name": "Priority support, annual",
                "quantity": 1,
                "unit_price": Decimal("600.00"),
                "line_total": Decimal("600.00"),
            },
            {
                "id": ORDER_ITEM_IDS["draft_workshop"],
                "order_id": ORDER_IDS["draft"],
                "product_id": PRODUCT_IDS["workshop"],
                "sku": "SRV-WS-02",
                "name": "Onboarding workshop",
                "quantity": 1,
                "unit_price": Decimal("2400.00"),
                "line_total": Decimal("2400.00"),
            },
            {
                "id": ORDER_ITEM_IDS["fulfilled_closed_order_only"],
                "order_id": ORDER_IDS["fulfilled"],
                "product_id": PRODUCT_IDS["closed_order_only"],
                "sku": "SRV-PILOT-05",
                "name": "One-time pilot engagement",
                "quantity": 1,
                "unit_price": Decimal("450.00"),
                "line_total": Decimal("450.00"),
            },
        ],
        conflict=["order_id", "product_id"],
        update=["sku", "name", "quantity", "unit_price", "line_total"],
    )


async def seed_settings(connection: AsyncConnection) -> None:
    await upsert(
        connection,
        table_of(OrganizationSetting),
        [
            {"id": uuid.uuid4(), "key": key, "value": value, "description": description}
            for key, value, description in (
                ("organization.name", "Training CRM", "Display name of the organization."),
                (
                    "organization.defaultCurrency",
                    "USD",
                    "Currency applied to new orders and deals.",
                ),
                ("orders.numberPrefix", "ORD", "Prefix used when generating order numbers."),
                (
                    "warehouse.defaultCode",
                    "CENTRAL",
                    "Warehouse used when a request does not name one.",
                ),
            )
        ],
        conflict=["key"],
        update=["value", "description"],
    )


async def seed() -> None:
    password_hash = hash_password(read_seed_password())
    engine = create_async_engine(get_settings().database_url)

    try:
        # One transaction: a partially seeded database is worse than none.
        async with engine.begin() as connection:
            roles, _ = await seed_rbac(connection)
            await seed_users(connection, roles, password_hash)
            await seed_crm(connection)
            await seed_catalogue(connection)
            await seed_orders(connection)
            await seed_settings(connection)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
