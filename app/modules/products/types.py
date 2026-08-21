"""Vocabulary of the product catalogue."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from app.db.enums import PermissionScope

__all__ = [
    "INVALID_PRODUCT_PRICE",
    "PRODUCT_CREATED",
    "PRODUCT_DELETED",
    "PRODUCT_ENTITY_TYPE",
    "PRODUCT_NOT_FOUND",
    "PRODUCT_SKU_TAKEN",
    "PRODUCT_UPDATED",
    "ProductAccess",
    "ProductSortField",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side.
PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
PRODUCT_SKU_TAKEN = "PRODUCT_SKU_TAKEN"
#: Optimistic locking is reported per resource, so a client editing several
#: records in one workflow knows which one to re-read.
PRODUCT_CONCURRENT_MODIFICATION = "PRODUCT_CONCURRENT_MODIFICATION"
INVALID_PRODUCT_PRICE = "INVALID_PRODUCT_PRICE"

#: One name for the catalogue in the audit trail and in the event log.
PRODUCT_ENTITY_TYPE = "product"

PRODUCT_CREATED = "product.created"
PRODUCT_UPDATED = "product.updated"
PRODUCT_DELETED = "product.deleted"


class ProductSortField(enum.StrEnum):
    """Columns a caller may order the catalogue by.

    A closed set rather than a free string: the value ends up in an ``ORDER BY``
    clause, and accepting whatever arrives would make that clause caller-written
    SQL. The values are the wire spelling, the service maps them to columns.
    """

    CREATED_AT = "createdAt"
    UPDATED_AT = "updatedAt"
    NAME = "name"
    SKU = "sku"
    UNIT_PRICE = "unitPrice"
    CATEGORY = "category"


@dataclass(frozen=True, slots=True)
class ProductAccess:
    """Who is asking, how widely they may act, and from where.

    The catalogue has no owner column, so ``scope`` only decides whether the
    caller may touch products at all; unlike deals it never narrows a result
    set. The address is what the audit entry is stamped with.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None
