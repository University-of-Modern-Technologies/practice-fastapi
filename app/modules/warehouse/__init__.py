"""Warehouses, stock levels and the ledger of movements between them.

Two entry points leave this package: the HTTP router, and the stock port that a
module driving its own transaction uses to move stock inside it.
"""

from __future__ import annotations

from app.modules.warehouse.operations import StockOperations, create_stock_operations
from app.modules.warehouse.router import create_warehouse_router, get_warehouse_service
from app.modules.warehouse.service import StockChange, WarehouseService
from app.modules.warehouse.types import (
    WAREHOUSE_RESOURCE,
    StockActor,
    StockAdjustmentInput,
    StockOperationInput,
    WarehouseAccess,
)

__all__ = [
    "WAREHOUSE_RESOURCE",
    "StockActor",
    "StockAdjustmentInput",
    "StockChange",
    "StockOperationInput",
    "StockOperations",
    "WarehouseAccess",
    "WarehouseService",
    "create_stock_operations",
    "create_warehouse_router",
    "get_warehouse_service",
]
