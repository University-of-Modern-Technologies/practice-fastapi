"""Product catalogue: the articles every order line is priced from.

Mount with ``create_products_router()`` under ``/api/v1/products``.
"""

from __future__ import annotations

from app.modules.products.router import create_products_router, get_products_service
from app.modules.products.schemas import (
    CreateProductRequest,
    ProductListParams,
    ProductOut,
    UpdateProductRequest,
)
from app.modules.products.service import ProductsService, to_product_out
from app.modules.products.types import ProductAccess, ProductSortField

__all__ = [
    "CreateProductRequest",
    "ProductAccess",
    "ProductListParams",
    "ProductOut",
    "ProductSortField",
    "ProductsService",
    "UpdateProductRequest",
    "create_products_router",
    "get_products_service",
    "to_product_out",
]
