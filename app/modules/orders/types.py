"""Vocabulary of the orders module.

The machine codes live here rather than next to the ``raise`` that uses them so
that the service, the router and the tests all name a failure the same way: a
rename cannot then pass unnoticed on one side.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.enums import PermissionScope

__all__ = [
    "CONTACT_NOT_FOUND",
    "DEAL_NOT_FOUND",
    "INVALID_ITEM_QUANTITY",
    "INVALID_MONETARY_AMOUNT",
    "INVALID_ORDER_STATUS_TRANSITION",
    "ORDER_CURRENCY_MISMATCH",
    "ORDER_ENTITY_TYPE",
    "ORDER_HAS_NO_ITEMS",
    "ORDER_ITEM_DUPLICATE",
    "ORDER_ITEM_NOT_FOUND",
    "ORDER_NOT_EDITABLE",
    "ORDER_NOT_FOUND",
    "ORDER_NUMBER_UNAVAILABLE",
    "ORDER_TOTALS_INVALID",
    "PRODUCT_INACTIVE",
    "PRODUCT_NOT_FOUND",
    "WAREHOUSE_NOT_CONFIGURED",
    "OrderAccess",
    "OrderSortField",
    "OrderStockEffect",
]

ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
#: Optimistic locking is reported per resource: a checkout touching both the
#: order and a stock level has to know which of them to re-read.
ORDER_CONCURRENT_MODIFICATION = "ORDER_CONCURRENT_MODIFICATION"
ORDER_ITEM_NOT_FOUND = "ORDER_ITEM_NOT_FOUND"
ORDER_ITEM_DUPLICATE = "ORDER_ITEM_DUPLICATE"
ORDER_NOT_EDITABLE = "ORDER_NOT_EDITABLE"
ORDER_HAS_NO_ITEMS = "ORDER_HAS_NO_ITEMS"
ORDER_NUMBER_UNAVAILABLE = "ORDER_NUMBER_UNAVAILABLE"
ORDER_CURRENCY_MISMATCH = "ORDER_CURRENCY_MISMATCH"
ORDER_TOTALS_INVALID = "ORDER_TOTALS_INVALID"
INVALID_ORDER_STATUS_TRANSITION = "INVALID_ORDER_STATUS_TRANSITION"
INVALID_MONETARY_AMOUNT = "INVALID_MONETARY_AMOUNT"
INVALID_ITEM_QUANTITY = "INVALID_ITEM_QUANTITY"
PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
PRODUCT_INACTIVE = "PRODUCT_INACTIVE"
CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"
DEAL_NOT_FOUND = "DEAL_NOT_FOUND"
WAREHOUSE_NOT_CONFIGURED = "WAREHOUSE_NOT_CONFIGURED"

#: What the audit trail, the event log and the realtime topics call an order.
ORDER_ENTITY_TYPE = "order"

#: The three stock effects an order lifecycle can have. Declared here — rather
#: than in ``stock.py`` — so that ``state.py`` can describe a status without
#: importing the stock module, which would otherwise import the state back to
#: compute ``stock_effect_for_transition``.
OrderStockEffect = Literal["reserve", "release", "issue"]

#: Columns a client may order the collection by, spelled as they arrive.
OrderSortField = Literal[
    "createdAt",
    "updatedAt",
    "orderNumber",
    "total",
    "placedAt",
    "status",
]


@dataclass(frozen=True, slots=True)
class OrderAccess:
    """Who is acting, and how wide their grant is.

    Carried as one value rather than three parameters because every service
    method needs all of it, and because the stock port is handed the very same
    object: the movement it writes is attributed to the same actor.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None
