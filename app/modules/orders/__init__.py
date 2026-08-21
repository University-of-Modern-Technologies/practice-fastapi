"""Sales orders: lines, money, the lifecycle and the stock it moves.

The module owns the arithmetic of an order (:mod:`money`), its lifecycle
(:mod:`transition`) and the port through which a status change moves goods
(:mod:`stock`). The port is declared here and implemented elsewhere, which is
what keeps the dependency between orders and the warehouse pointing one way.
"""

from __future__ import annotations

from app.modules.orders.money import (
    ZERO_MONEY,
    OrderTotals,
    calculate_line_total,
    calculate_order_totals,
    normalize_money,
)
from app.modules.orders.router import (
    OrdersServiceDep,
    create_orders_router,
    get_orders_service,
    get_orders_stock,
)
from app.modules.orders.schemas import OrderItemOut, OrderListParams, OrderOut
from app.modules.orders.service import OrdersService
from app.modules.orders.stock import (
    ORDER_STOCK_REFERENCE_TYPE,
    NoopStockOperations,
    OrdersStockPort,
    OrderStockChange,
    OrderStockEffect,
    OrderStockInput,
    OrderStockOperations,
    OrderWarehouseResolver,
    stock_effect_for_transition,
)
from app.modules.orders.transition import (
    ALLOWED_ORDER_STATUS_TRANSITIONS,
    can_transition_order_status,
    is_order_editable,
)
from app.modules.orders.types import ORDER_ENTITY_TYPE, OrderAccess

__all__ = [
    "ALLOWED_ORDER_STATUS_TRANSITIONS",
    "ORDER_ENTITY_TYPE",
    "ORDER_STOCK_REFERENCE_TYPE",
    "ZERO_MONEY",
    "NoopStockOperations",
    "OrderAccess",
    "OrderItemOut",
    "OrderListParams",
    "OrderOut",
    "OrderStockChange",
    "OrderStockEffect",
    "OrderStockInput",
    "OrderStockOperations",
    "OrderTotals",
    "OrderWarehouseResolver",
    "OrdersService",
    "OrdersServiceDep",
    "OrdersStockPort",
    "calculate_line_total",
    "calculate_order_totals",
    "can_transition_order_status",
    "create_orders_router",
    "get_orders_service",
    "get_orders_stock",
    "is_order_editable",
    "normalize_money",
    "stock_effect_for_transition",
]
