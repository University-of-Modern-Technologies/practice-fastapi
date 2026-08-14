"""Metadata-level checks on the mapped schema.

No database is involved: everything here is answerable from ``Base.metadata``,
which is what makes the suite runnable anywhere and fast enough to run often.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import class_mapper

import app.db.models  # noqa: F401  # registers every mapping
from app.db.base import Base
from app.db.enums import DealStage, OrderStatus, PermissionScope, StockMovementType

EXPECTED_TABLES = {
    "audit_logs",
    "contacts",
    "deals",
    "order_items",
    "orders",
    "organization_settings",
    "permissions",
    "products",
    "role_permissions",
    "roles",
    "sessions",
    "stock_levels",
    "stock_movements",
    "user_roles",
    "users",
    "warehouses",
}

EXPECTED_COLUMNS = {
    "users": {
        "id",
        "email",
        "password_hash",
        "name",
        "is_active",
        "created_at",
        "updated_at",
    },
    "sessions": {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "revoked_at",
        "ip_address",
        "user_agent",
        "created_at",
        "updated_at",
    },
    "deals": {
        "id",
        "owner_id",
        "contact_id",
        "title",
        "stage",
        "amount",
        "currency",
        "probability",
        "version",
        "expected_close_date",
        "closed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "orders": {
        "id",
        "order_number",
        "owner_id",
        "contact_id",
        "deal_id",
        "status",
        "currency",
        "subtotal",
        "discount_total",
        "tax_total",
        "total",
        "notes",
        "version",
        "placed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "audit_logs": {
        "id",
        "actor_id",
        "action",
        "entity_type",
        "entity_id",
        "changes",
        "metadata",
        "ip_address",
        "created_at",
    },
}

EXPECTED_COMPOSITE_UNIQUES = {
    ("order_items", ("order_id", "product_id")),
    ("stock_levels", ("warehouse_id", "product_id")),
}

EXPECTED_COMPOSITE_PRIMARY_KEYS = {
    ("user_roles", ("user_id", "role_id")),
    ("role_permissions", ("role_id", "permission_id")),
}

#: Every index the migration is expected to create, by name.
EXPECTED_INDEXES = {
    "audit_logs_action_created_at_idx",
    "audit_logs_actor_id_created_at_idx",
    "audit_logs_entity_type_entity_id_created_at_idx",
    "contacts_company_idx",
    "contacts_email_idx",
    "contacts_last_name_first_name_idx",
    "contacts_owner_id_deleted_at_idx",
    "deals_contact_id_idx",
    "deals_deleted_at_idx",
    "deals_owner_id_stage_deleted_at_idx",
    "deals_stage_expected_close_date_idx",
    "order_items_product_id_idx",
    "orders_contact_id_idx",
    "orders_deal_id_idx",
    "orders_deleted_at_idx",
    "orders_owner_id_status_deleted_at_idx",
    "orders_status_placed_at_idx",
    "products_category_is_active_idx",
    "products_deleted_at_idx",
    "products_name_idx",
    "role_permissions_permission_id_idx",
    "sessions_expires_at_idx",
    "sessions_user_id_expires_at_idx",
    "stock_levels_product_id_idx",
    "stock_movements_reference_type_reference_id_idx",
    "stock_movements_type_created_at_idx",
    "stock_movements_warehouse_id_product_id_created_at_idx",
    "user_roles_role_id_idx",
    "users_is_active_idx",
}

MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0001_initial.py"


def _literal_arguments(call: ast.Call) -> list[str]:
    return [
        arg.value
        for arg in call.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def _migration_calls(function: str) -> list[str]:
    """First literal argument of every ``op.<function>`` call in the migration."""
    tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == function
        ):
            arguments = _literal_arguments(node)
            if arguments:
                names.append(arguments[0])
    return names


def test_every_table_is_mapped() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


@pytest.mark.parametrize(("table_name", "columns"), sorted(EXPECTED_COLUMNS.items()))
def test_columns_match_the_contract(table_name: str, columns: set[str]) -> None:
    table = Base.metadata.tables[table_name]
    assert {column.name for column in table.columns} == columns


@pytest.mark.parametrize(("table_name", "columns"), sorted(EXPECTED_COMPOSITE_UNIQUES))
def test_composite_unique_constraints_exist(table_name: str, columns: tuple[str, ...]) -> None:
    table = Base.metadata.tables[table_name]
    found = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert columns in found


@pytest.mark.parametrize(("table_name", "columns"), sorted(EXPECTED_COMPOSITE_PRIMARY_KEYS))
def test_composite_primary_keys_exist(table_name: str, columns: tuple[str, ...]) -> None:
    table = Base.metadata.tables[table_name]
    assert tuple(column.name for column in table.primary_key.columns) == columns


def test_enum_values_match_the_wire_labels() -> None:
    assert [member.value for member in PermissionScope] == ["ALL", "OWN"]
    assert [member.value for member in DealStage] == [
        "LEAD",
        "QUALIFIED",
        "PROPOSAL",
        "WON",
        "LOST",
    ]
    assert [member.value for member in OrderStatus] == [
        "DRAFT",
        "CONFIRMED",
        "PAID",
        "FULFILLED",
        "CANCELLED",
    ]
    assert [member.value for member in StockMovementType] == [
        "RECEIPT",
        "ISSUE",
        "RESERVATION",
        "RELEASE",
        "ADJUSTMENT",
    ]


def test_enum_columns_persist_values_rather_than_member_names() -> None:
    stage = Base.metadata.tables["deals"].columns["stage"].type
    assert isinstance(stage, SAEnum)
    assert stage.name == "DealStage"
    assert stage.enums == ["LEAD", "QUALIFIED", "PROPOSAL", "WON", "LOST"]


def test_no_relationship_loads_lazily() -> None:
    """A lazy load in async code fails at a distance; ``raise`` fails at once."""
    offenders = [
        f"{mapper.class_.__name__}.{relationship.key}"
        for mapper in Base.registry.mappers
        for relationship in mapper.relationships
        if relationship.lazy != "raise"
    ]
    assert offenders == []


def test_every_model_is_mapped_to_a_real_table() -> None:
    for mapper in Base.registry.mappers:
        assert isinstance(class_mapper(mapper.class_).local_table, Table)


def test_soft_deletable_tables_guard_the_deletion_timestamp() -> None:
    for table_name in ("contacts", "deals"):
        names = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert f"{table_name}_deleted_at_check" in names


def test_migration_creates_exactly_the_mapped_tables() -> None:
    assert set(_migration_calls("create_table")) == EXPECTED_TABLES


def test_migration_creates_exactly_the_mapped_indexes() -> None:
    metadata_indexes = {
        index.name for table in Base.metadata.tables.values() for index in table.indexes
    }
    assert metadata_indexes == EXPECTED_INDEXES
    assert set(_migration_calls("create_index")) == EXPECTED_INDEXES


def test_migration_drops_everything_it_created() -> None:
    assert set(_migration_calls("drop_table")) == EXPECTED_TABLES
