"""Path parameters carry the names the published contract gives them.

A handler keeps its snake_case argument while the path placeholder uses the
contract's name, so two things have to hold: a well-formed request still binds
every identifier to the right argument, and a malformed one is refused with the
contract's name for the parameter, since that name is what the client sent.

Authorization and the services are doubles: nothing here reaches storage.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.container import build_container
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.audit.router import get_audit_service
from app.modules.auth.dependencies import get_auth
from app.modules.auth.types import AuthContext
from app.modules.orders.router import get_orders_service
from app.modules.products.router import get_products_service
from app.modules.rbac.dependencies import get_rbac_service
from app.modules.users.router import get_users_service
from app.modules.warehouse.router import get_warehouse_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000002")
FIRST = uuid.UUID("20000000-0000-4000-8000-000000000001")
SECOND = uuid.UUID("20000000-0000-4000-8000-000000000002")
MALFORMED = "not-a-uuid"


class _AnyGrant:
    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope:
        del user_id, resource, action
        return PermissionScope.ALL


class _RecordingService:
    """Remembers the identifiers a call was given, then answers "not found".

    The refusal keeps the double from having to build a real response body:
    reaching the service with the right arguments is all these tests ask.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        async def call(*args: Any) -> None:
            self.calls.append((name, args))
            raise NotFoundError

        return call

    def identifiers(self) -> list[uuid.UUID]:
        return [value for _, args in self.calls for value in args if isinstance(value, uuid.UUID)]


@pytest.fixture
def service() -> _RecordingService:
    return _RecordingService()


@pytest.fixture
def app(settings: Settings, service: _RecordingService) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    application = create_app(settings, routers=build_container(settings).routers)
    application.dependency_overrides[get_auth] = lambda: AuthContext(
        user_id=USER_ID, session_id=SESSION_ID
    )
    application.dependency_overrides[get_rbac_service] = _AnyGrant
    for provider in (
        get_audit_service,
        get_orders_service,
        get_products_service,
        get_users_service,
        get_warehouse_service,
    ):
        application.dependency_overrides[provider] = lambda: service
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# (method, path with `{0}`/`{1}` for the identifiers, body, the parameter name
# the contract gives the identifier that is malformed in the refusal case).
ROUTES: list[tuple[str, str, dict[str, Any] | None, str]] = [
    ("GET", "/api/v1/products/{0}", None, "id"),
    ("PATCH", "/api/v1/products/{0}", {"version": 1, "name": "Desk"}, "id"),
    ("DELETE", "/api/v1/products/{0}?version=1", None, "id"),
    ("DELETE", f"/api/v1/users/{FIRST}/sessions/{{1}}", None, "sessionId"),
    ("PATCH", f"/api/v1/orders/{FIRST}/items/{{1}}", {"version": 1, "quantity": 1}, "itemId"),
    ("DELETE", f"/api/v1/orders/{FIRST}/items/{{1}}?version=1", None, "itemId"),
    ("GET", "/api/v1/audit/contacts/{1}", None, "resourceId"),
    ("GET", "/api/v1/audit/{0}", None, "id"),
    ("GET", f"/api/v1/warehouse/stock/{{0}}/{SECOND}", None, "warehouseId"),
    ("GET", f"/api/v1/warehouse/stock/{FIRST}/{{1}}", None, "productId"),
]


def _ids(route: tuple[str, str, dict[str, Any] | None, str]) -> str:
    return f"{route[0]} {route[1]}"


@pytest.mark.parametrize("route", ROUTES, ids=_ids)
async def test_a_malformed_identifier_is_refused_under_the_contract_name(
    client: AsyncClient,
    service: _RecordingService,
    route: tuple[str, str, dict[str, Any] | None, str],
) -> None:
    method, template, body, name = route
    path = template.format(MALFORMED, MALFORMED)

    response = await client.request(method, path, json=body)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["formErrors"] == []
    # Only the location group is shared with the sibling backend; the message
    # after the name is the validator's own wording.
    assert list(error["details"]["fieldErrors"]) == ["params"]
    messages = error["details"]["fieldErrors"]["params"]
    assert len(messages) == 1
    assert messages[0].startswith(f"{name}: ")
    assert service.calls == []


@pytest.mark.parametrize("route", ROUTES, ids=_ids)
async def test_a_well_formed_identifier_reaches_the_service(
    client: AsyncClient,
    service: _RecordingService,
    route: tuple[str, str, dict[str, Any] | None, str],
) -> None:
    method, template, body, _ = route

    response = await client.request(method, template.format(FIRST, SECOND), json=body)

    assert response.status_code == 404
    assert len(service.calls) == 1


async def test_two_identifiers_bind_in_the_order_the_path_names_them(
    client: AsyncClient, service: _RecordingService
) -> None:
    await client.get(f"/api/v1/warehouse/stock/{FIRST}/{SECOND}")

    assert service.calls == [("get_stock", (FIRST, SECOND))]


async def test_a_session_is_revoked_for_the_user_the_path_names(
    client: AsyncClient, service: _RecordingService
) -> None:
    await client.delete(f"/api/v1/users/{FIRST}/sessions/{SECOND}")

    # The first argument is the caller, recorded on the audit entry.
    [(name, args)] = service.calls
    assert (name, args[1:]) == ("revoke_session", (FIRST, SECOND))


async def test_an_order_item_is_addressed_within_its_order(
    client: AsyncClient, service: _RecordingService
) -> None:
    await client.delete(f"/api/v1/orders/{FIRST}/items/{SECOND}?version=1")

    assert service.identifiers() == [FIRST, SECOND]


async def test_the_history_reads_the_record_the_path_names(
    client: AsyncClient, service: _RecordingService
) -> None:
    await client.get(f"/api/v1/audit/contacts/{SECOND}")

    assert service.calls[0][0] == "history"
    assert service.calls[0][1][2:4] == ("contacts", SECOND)
