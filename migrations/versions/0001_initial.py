"""Initial schema: accounts, RBAC, CRM records, catalogue, orders and stock.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Constraint bodies long enough to deserve a name of their own.
PERMISSION_KEY_FORMAT = "key ~ '^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$'"
DEAL_STAGE_PROBABILITY = (
    "(stage = 'WON' AND probability = 100) OR "
    "(stage = 'LOST' AND probability = 0) OR "
    "(stage NOT IN ('WON', 'LOST') AND probability < 100)"
)
ORDER_TOTALS_NON_NEGATIVE = (
    "subtotal >= 0 AND discount_total >= 0 AND tax_total >= 0 AND total >= 0"
)
STOCK_QUANTITIES_NON_NEGATIVE = "quantity_on_hand >= 0 AND quantity_reserved >= 0"

#: Native enum types, dropped explicitly on downgrade because dropping a table
#: does not remove the type it referenced.
ENUM_TYPES = ("PermissionScope", "DealStage", "OrderStatus", "StockMovementType")


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(PERMISSION_KEY_FORMAT, name="key_format"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("currency", sa.CHAR(length=3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )
    op.create_index(
        "products_category_is_active_idx", "products", ["category", "is_active"], unique=False
    )
    op.create_index("products_deleted_at_idx", "products", ["deleted_at"], unique=False)
    op.create_index("products_name_idx", "products", ["name"], unique=False)

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("btrim(name) <> ''", name="name_nonempty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("btrim(email) <> ''", name="email_nonempty"),
        sa.CheckConstraint("btrim(name) <> ''", name="name_nonempty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("users_is_active_idx", "users", ["is_active"], unique=False)

    op.create_table(
        "warehouses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("btrim(action) <> ''", name="action_nonempty"),
        sa.CheckConstraint("btrim(entity_type) <> ''", name="entity_type_nonempty"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "audit_logs_action_created_at_idx", "audit_logs", ["action", "created_at"], unique=False
    )
    op.create_index(
        "audit_logs_actor_id_created_at_idx", "audit_logs", ["actor_id", "created_at"], unique=False
    )
    op.create_index(
        "audit_logs_entity_type_entity_id_created_at_idx",
        "audit_logs",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.CheckConstraint("deleted_at IS NULL OR deleted_at >= created_at", name="deleted_at"),
        sa.CheckConstraint("btrim(first_name) <> ''", name="first_name_nonempty"),
        sa.CheckConstraint("btrim(last_name) <> ''", name="last_name_nonempty"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("contacts_company_idx", "contacts", ["company"], unique=False)
    op.create_index("contacts_email_idx", "contacts", ["email"], unique=False)
    op.create_index(
        "contacts_last_name_first_name_idx", "contacts", ["last_name", "first_name"], unique=False
    )
    op.create_index(
        "contacts_owner_id_deleted_at_idx", "contacts", ["owner_id", "deleted_at"], unique=False
    )

    op.create_table(
        "organization_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Enum("ALL", "OWN", name="PermissionScope"), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    op.create_index(
        "role_permissions_permission_id_idx", "role_permissions", ["permission_id"], unique=False
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=False),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry"),
        sa.CheckConstraint("btrim(token_hash) <> ''", name="token_hash_nonempty"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("sessions_expires_at_idx", "sessions", ["expires_at"], unique=False)
    op.create_index(
        "sessions_user_id_expires_at_idx", "sessions", ["user_id", "expires_at"], unique=False
    )

    op.create_table(
        "stock_levels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(STOCK_QUANTITIES_NON_NEGATIVE, name="quantities_non_negative"),
        sa.CheckConstraint("quantity_reserved <= quantity_on_hand", name="reserved_within_on_hand"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "product_id"),
    )
    op.create_index("stock_levels_product_id_idx", "stock_levels", ["product_id"], unique=False)

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "RECEIPT", "ISSUE", "RESERVATION", "RELEASE", "ADJUSTMENT", name="StockMovementType"
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "stock_movements_reference_type_reference_id_idx",
        "stock_movements",
        ["reference_type", "reference_id"],
        unique=False,
    )
    op.create_index(
        "stock_movements_type_created_at_idx",
        "stock_movements",
        ["type", "created_at"],
        unique=False,
    )
    op.create_index(
        "stock_movements_warehouse_id_product_id_created_at_idx",
        "stock_movements",
        ["warehouse_id", "product_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_index("user_roles_role_id_idx", "user_roles", ["role_id"], unique=False)

    op.create_table(
        "deals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column(
            "stage",
            sa.Enum("LEAD", "QUALIFIED", "PROPOSAL", "WON", "LOST", name="DealStage"),
            nullable=False,
            server_default=sa.text("'LEAD'"),
        ),
        sa.Column(
            "amount", sa.Numeric(precision=14, scale=2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("currency", sa.CHAR(length=3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("probability", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("closed_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.CheckConstraint("amount >= 0", name="amount_nonnegative"),
        sa.CheckConstraint("closed_at IS NULL OR closed_at >= created_at", name="closed_at"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        sa.CheckConstraint("deleted_at IS NULL OR deleted_at >= created_at", name="deleted_at"),
        sa.CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
        sa.CheckConstraint(DEAL_STAGE_PROBABILITY, name="stage_probability"),
        sa.CheckConstraint("btrim(title) <> ''", name="title_nonempty"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("deals_contact_id_idx", "deals", ["contact_id"], unique=False)
    op.create_index("deals_deleted_at_idx", "deals", ["deleted_at"], unique=False)
    op.create_index(
        "deals_owner_id_stage_deleted_at_idx",
        "deals",
        ["owner_id", "stage", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "deals_stage_expected_close_date_idx",
        "deals",
        ["stage", "expected_close_date"],
        unique=False,
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "CONFIRMED", "PAID", "FULFILLED", "CANCELLED", name="OrderStatus"),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("currency", sa.CHAR(length=3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column(
            "subtotal",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "discount_total",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tax_total",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total", sa.Numeric(precision=14, scale=2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("placed_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.CheckConstraint(ORDER_TOTALS_NON_NEGATIVE, name="totals_non_negative"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number"),
    )
    op.create_index("orders_contact_id_idx", "orders", ["contact_id"], unique=False)
    op.create_index("orders_deal_id_idx", "orders", ["deal_id"], unique=False)
    op.create_index("orders_deleted_at_idx", "orders", ["deleted_at"], unique=False)
    op.create_index(
        "orders_owner_id_status_deleted_at_idx",
        "orders",
        ["owner_id", "status", "deleted_at"],
        unique=False,
    )
    op.create_index("orders_status_placed_at_idx", "orders", ["status", "placed_at"], unique=False)

    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("line_total >= 0", name="line_total_non_negative"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "product_id"),
    )
    op.create_index("order_items_product_id_idx", "order_items", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("deals")
    op.drop_table("user_roles")
    op.drop_table("stock_movements")
    op.drop_table("stock_levels")
    op.drop_table("sessions")
    op.drop_table("role_permissions")
    op.drop_table("organization_settings")
    op.drop_table("contacts")
    op.drop_table("audit_logs")
    op.drop_table("warehouses")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("products")
    op.drop_table("permissions")
    for enum_name in ENUM_TYPES:
        op.execute(f'DROP TYPE IF EXISTS "{enum_name}"')
