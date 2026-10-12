"""A deal amount crosses the wire as a decimal string, and only as one.

The model-level rules are covered with the schemas; these tests look at what a
client observes over HTTP and at what the published description promises, so
the two cannot disagree about whether a JSON number is acceptable.

Authorization and the service are doubles: nothing here reaches storage.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.auth.dependencies import get_auth
from app.modules.auth.types import AuthContext
from app.modules.deals.router import create_deals_router, get_deals_service
from app.modules.rbac.dependencies import get_rbac_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000003")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000003")
DEAL_ID = uuid.UUID("50000000-0000-4000-8000-000000000001")
PREFIX = "/api/v1/deals"


class _AnyGrant:
    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope:
        del user_id, resource, action
        return PermissionScope.ALL


class _RecordingDeals:
    """Keeps the payload it was handed, then answers "not found"."""

    def __init__(self) -> None:
        self.payloads: list[Any] = []

    async def create(self, _access: object, payload: Any) -> None:
        self.payloads.append(payload)
        raise NotFoundError

    async def update(self, _access: object, _deal_id: uuid.UUID, payload: Any) -> None:
        self.payloads.append(payload)
        raise NotFoundError


@pytest.fixture
def deals() -> _RecordingDeals:
    return _RecordingDeals()


@pytest.fixture
def app(settings: Settings, deals: _RecordingDeals) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    application = create_app(settings, routers=[(PREFIX, create_deals_router())])
    application.dependency_overrides[get_auth] = lambda: AuthContext(
        user_id=USER_ID, session_id=SESSION_ID
    )
    application.dependency_overrides[get_rbac_service] = _AnyGrant
    application.dependency_overrides[get_deals_service] = lambda: deals
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# (method, path, the body without its amount)
WRITES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", PREFIX, {"title": "Opportunity"}),
    ("PATCH", f"{PREFIX}/{DEAL_ID}", {"version": 1}),
]


@pytest.mark.parametrize("amount", [1250, 12.5])
@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_a_json_number_amount_is_refused(  # noqa: PLR0913, PLR0917
    client: AsyncClient,
    deals: _RecordingDeals,
    method: str,
    path: str,
    body: dict[str, Any],
    amount: float,
) -> None:
    response = await client.request(method, path, json={**body, "amount": amount})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [message.split(":")[0] for message in error["details"]["fieldErrors"]["body"]] == [
        "amount"
    ]
    assert deals.payloads == []


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_a_decimal_string_amount_reaches_the_service(
    client: AsyncClient,
    deals: _RecordingDeals,
    method: str,
    path: str,
    body: dict[str, Any],
) -> None:
    response = await client.request(method, path, json={**body, "amount": "1250.50"})

    assert response.status_code == 404
    assert [payload.amount for payload in deals.payloads] == [Decimal("1250.50")]


def test_the_description_publishes_the_amount_as_a_string_only(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]
    created = schemas["CreateDealRequest"]["properties"]["amount"]
    updated = schemas["UpdateDealRequest"]["properties"]["amount"]

    assert created["type"] == "string"
    assert [variant["type"] for variant in updated["anyOf"]] == ["string", "null"]
