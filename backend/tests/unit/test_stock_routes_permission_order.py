"""Orders, products and warehouse refuse a missing grant before a bad request.

A caller without the permission learns nothing about the shape the endpoint
expects: the 403 comes first, and only a caller who holds the grant is told
what is wrong with the body, the query or the path. The sibling backend answers
in the same order, so a client sees the same refusal from either.

Authorization and the services are doubles: nothing here reaches storage.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.container import build_container
from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.auth.dependencies import get_auth
from app.modules.auth.types import AuthContext
from app.modules.orders.router import get_orders_service
from app.modules.products.router import get_products_service
from app.modules.rbac.dependencies import get_rbac_service
from app.modules.warehouse.router import get_warehouse_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000003")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000003")
ORDER_ID = uuid.UUID("20000000-0000-4000-8000-000000000003")


class _Grant:
    """Answers every permission question with one fixed scope, or none."""

    def __init__(self, scope: PermissionScope | None) -> None:
        self._scope = scope

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope | None:
        del user_id, resource, action
        return self._scope


class _UnreachableService:
    """Fails loudly if a refused request ever got as far as the service."""

    def __getattr__(self, name: str) -> Any:
        message = f"the service was reached ({name})"
        raise AssertionError(message)


def _app(settings: Settings, scope: PermissionScope | None) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    application = create_app(settings, routers=build_container(settings).routers)
    application.dependency_overrides[get_auth] = lambda: AuthContext(
        user_id=USER_ID, session_id=SESSION_ID
    )
    application.dependency_overrides[get_rbac_service] = lambda: _Grant(scope)
    for provider in (get_orders_service, get_products_service, get_warehouse_service):
        application.dependency_overrides[provider] = _UnreachableService
    return application


async def _client(application: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def ungranted(settings: Settings) -> AsyncIterator[AsyncClient]:
    async for http in _client(_app(settings, None)):
        yield http


@pytest.fixture
async def granted(settings: Settings) -> AsyncIterator[AsyncClient]:
    async for http in _client(_app(settings, PermissionScope.ALL)):
        yield http


# Each request is malformed in its body, query or path.
MALFORMED: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/api/v1/orders", {"items": "not-a-list"}),
    ("GET", "/api/v1/orders/not-a-uuid", None),
    ("POST", f"/api/v1/orders/{ORDER_ID}/transitions", {"version": 0, "status": "NOPE"}),
    ("GET", "/api/v1/products?pageSize=1000", None),
    ("POST", "/api/v1/products", {"sku": ""}),
    (
        "POST",
        "/api/v1/warehouse/stock/adjust",
        {"warehouseId": str(ORDER_ID), "productId": str(ORDER_ID), "delta": 0},
    ),
]


def _ids(route: tuple[str, str, dict[str, Any] | None]) -> str:
    return f"{route[0]} {route[1]}"


@pytest.mark.parametrize("route", MALFORMED, ids=_ids)
async def test_a_caller_without_the_grant_is_refused_before_the_request_is_checked(
    ungranted: AsyncClient, route: tuple[str, str, dict[str, Any] | None]
) -> None:
    method, path, body = route

    response = await ungranted.request(method, path, json=body)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("route", MALFORMED, ids=_ids)
async def test_a_caller_with_the_grant_is_told_what_is_wrong_with_the_request(
    granted: AsyncClient, route: tuple[str, str, dict[str, Any] | None]
) -> None:
    method, path, body = route

    response = await granted.request(method, path, json=body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
