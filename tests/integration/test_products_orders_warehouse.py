"""Scenario 6 — a product read across orders and warehouse together.

The one integration suite that crosses `products`, `orders` and `warehouse` —
the three modules the product-archiving task bank entry touches. Nothing here
tests archiving itself (it does not exist yet); it is a style sample for the
change that adds it, showing how a product, an order that references it, and
a stock level are built together against the live database.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.db.enums import OrderStatus, PermissionScope
from app.modules.orders.schemas import CreateOrderRequest, OrderItemRequest
from app.modules.orders.service import OrdersService
from app.modules.orders.types import PRODUCT_INACTIVE, OrderAccess
from app.modules.products.schemas import UpdateProductRequest
from app.modules.products.service import ProductsService
from app.modules.products.types import ProductAccess
from app.modules.warehouse.schemas import ReceiveStockRequest, ReserveStockRequest
from app.modules.warehouse.service import WarehouseService
from app.modules.warehouse.types import WarehouseAccess
from tests.integration.conftest import create_order, create_product, create_user, create_warehouse

ORDER_REFERENCE = "order"


async def test_a_deactivated_product_is_refused_by_new_orders_but_not_by_warehouse(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    warehouse = await create_warehouse(db_session)
    product = await create_product(db_session)

    warehouse_service = WarehouseService(db_session)
    warehouse_access = WarehouseAccess(actor_id=owner.id, scope=PermissionScope.ALL)
    await warehouse_service.receive(
        warehouse_access,
        ReceiveStockRequest(warehouse_id=warehouse.id, product_id=product.id, quantity=10),
    )

    # The existing guard the task bank names as the style sample: an order
    # for an active product succeeds, and confirming it puts the product in an
    # open order — the state a "may this product be archived" check reads.
    orders_service = OrdersService(db_session)
    orders_access = OrderAccess(actor_id=owner.id, scope=PermissionScope.ALL)
    order = await create_order(db_session, owner, product, quantity=2, status=OrderStatus.CONFIRMED)
    assert order.status is OrderStatus.CONFIRMED

    products_service = ProductsService(db_session)
    products_access = ProductAccess(actor_id=owner.id, scope=PermissionScope.ALL)
    deactivated = await products_service.update(
        products_access,
        product.id,
        UpdateProductRequest(version=product.version, is_active=False),
    )
    assert deactivated.is_active is False

    with pytest.raises(ConflictError) as excinfo:
        await orders_service.create(
            orders_access,
            CreateOrderRequest(
                owner_id=owner.id,
                items=[OrderItemRequest(product_id=product.id, quantity=1)],
            ),
        )
    assert excinfo.value.code == PRODUCT_INACTIVE

    # Warehouse movements do not look at the product at all — the exact gap
    # the task bank entry asks the change to close.
    reserved = await warehouse_service.reserve(
        warehouse_access,
        ReserveStockRequest(
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity=1,
            reference_type=ORDER_REFERENCE,
            reference_id=order.id,
        ),
    )
    assert reserved.quantity_reserved == 1
