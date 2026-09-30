"""The HTTP contract of the integrations endpoints.

Authorization is replaced by a double so that these tests are about what a
client observes: the paths, the status codes, the envelope, and the fact that a
bad payload is refused before it can reach a third party.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.auth.dependencies import get_auth, get_auth_service
from app.modules.auth.types import AuthContext
from app.modules.integrations.delivery.factory import create_configured_delivery_client
from app.modules.integrations.router import create_integrations_router
from app.modules.rbac.dependencies import get_rbac_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000002")
PREFIX = "/api/v1/integrations"

ADDRESS = {"country": "PL", "city": "Warsaw", "postalCode": "00-001", "line1": "Street 1"}
PARCEL = {"weightGrams": 1_000, "lengthCm": 10, "widthCm": 10, "heightCm": 10}
QUOTE_BODY: dict[str, Any] = {
    "orderId": "ord_1",
    "origin": ADDRESS,
    "destination": {**ADDRESS, "country": "DE", "city": "Berlin", "postalCode": "10115"},
    "parcel": PARCEL,
}


class FakeRbacService:
    """Grants whatever the test says, and records what was asked."""

    def __init__(self, granted: dict[str, PermissionScope]) -> None:
        self._granted = granted
        self.asked: list[tuple[str, str]] = []

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope | None:
        del user_id
        self.asked.append((resource, action))
        return self._granted.get(action)


@pytest.fixture
def granted() -> dict[str, PermissionScope]:
    return {"read": PermissionScope.ALL, "write": PermissionScope.ALL}


@pytest.fixture
def rbac(granted: dict[str, PermissionScope]) -> FakeRbacService:
    return FakeRbacService(granted)


@pytest.fixture
def integrations_app(settings: Settings, rbac: FakeRbacService) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=[(PREFIX, create_integrations_router())])
    app.state.settings = settings
    # The client is normally published by the composition root; a stub-backed
    # one keeps the breaker state stable across the requests of one test.
    app.state.delivery_client = create_configured_delivery_client()
    app.dependency_overrides[get_auth] = lambda: AuthContext(user_id=USER_ID, session_id=SESSION_ID)
    app.dependency_overrides[get_rbac_service] = lambda: rbac
    return app


@pytest.fixture
async def integrations_client(integrations_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=integrations_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_health_reports_the_transport_and_the_circuit(
    integrations_client: AsyncClient,
) -> None:
    response = await integrations_client.get(f"{PREFIX}/health")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "transport": "stub",
            "circuitState": "closed",
            "consecutiveFailures": 0,
            "lastErrorAt": None,
            "openedAt": None,
        }
    }


async def test_a_quote_is_returned_inside_the_envelope(integrations_client: AsyncClient) -> None:
    response = await integrations_client.post(f"{PREFIX}/delivery/quotes", json=QUOTE_BODY)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["carrier"] == "Stub Express"
    assert data["amount"] == "7.49"
    assert data["currency"] == "EUR"
    assert data["expiresAt"].endswith("Z")


async def test_a_shipment_is_created_with_201_and_can_then_be_tracked(
    integrations_client: AsyncClient,
) -> None:
    quote = (await integrations_client.post(f"{PREFIX}/delivery/quotes", json=QUOTE_BODY)).json()[
        "data"
    ]

    created = await integrations_client.post(
        f"{PREFIX}/delivery/shipments",
        json={
            "quoteId": quote["quoteId"],
            "orderId": QUOTE_BODY["orderId"],
            "destination": QUOTE_BODY["destination"],
            "parcel": QUOTE_BODY["parcel"],
        },
    )

    assert created.status_code == 201
    shipment = created.json()["data"]
    assert shipment["status"] == "CREATED"
    assert shipment["orderId"] == "ord_1"

    tracked = await integrations_client.get(f"{PREFIX}/delivery/shipments/{shipment['shipmentId']}")
    assert tracked.status_code == 200
    assert tracked.json()["data"]["status"] == "IN_TRANSIT"


async def test_an_unknown_shipment_is_reported_as_rejected_by_the_carrier(
    integrations_client: AsyncClient,
) -> None:
    response = await integrations_client.get(f"{PREFIX}/delivery/shipments/shp_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DELIVERY_REJECTED"


async def test_a_malformed_quote_is_refused_before_it_reaches_the_carrier(
    integrations_client: AsyncClient,
) -> None:
    response = await integrations_client.post(
        f"{PREFIX}/delivery/quotes",
        json={**QUOTE_BODY, "parcel": {**PARCEL, "weightGrams": 0}},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_an_unknown_country_code_is_refused(integrations_client: AsyncClient) -> None:
    response = await integrations_client.post(
        f"{PREFIX}/delivery/quotes",
        json={**QUOTE_BODY, "origin": {**ADDRESS, "country": "Poland"}},
    )

    assert response.status_code == 400


async def test_an_unknown_field_in_the_body_is_ignored_rather_than_refused(
    integrations_client: AsyncClient,
) -> None:
    response = await integrations_client.post(
        f"{PREFIX}/delivery/quotes", json={**QUOTE_BODY, "somethingElse": True}
    )

    assert response.status_code == 200


async def test_creating_a_shipment_needs_the_write_permission(
    integrations_client: AsyncClient, granted: dict[str, PermissionScope], rbac: FakeRbacService
) -> None:
    del granted["write"]

    response = await integrations_client.post(
        f"{PREFIX}/delivery/shipments",
        json={
            "quoteId": "qte_1",
            "orderId": "ord_1",
            "destination": QUOTE_BODY["destination"],
            "parcel": PARCEL,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert ("integrations", "write") in rbac.asked


async def test_reading_needs_the_read_permission(
    integrations_client: AsyncClient, granted: dict[str, PermissionScope]
) -> None:
    granted.clear()

    for method, path in (
        ("GET", f"{PREFIX}/health"),
        ("GET", f"{PREFIX}/delivery/shipments/shp_1"),
    ):
        response = await integrations_client.request(method, path)
        assert response.status_code == 403


async def test_an_anonymous_caller_is_rejected(
    integrations_app: FastAPI, settings: Settings
) -> None:
    del settings
    integrations_app.dependency_overrides.pop(get_auth)
    # A request with no bearer never reaches the auth service, so a placeholder
    # is enough to keep the dependency graph off the database.
    integrations_app.dependency_overrides[get_auth_service] = lambda: None
    transport = ASGITransport(app=integrations_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"{PREFIX}/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_the_openapi_schema_advertises_the_four_documented_paths(
    integrations_app: FastAPI,
) -> None:
    schema = integrations_app.openapi()

    paths = {path for path in schema["paths"] if path.startswith(PREFIX)}
    assert paths == {
        f"{PREFIX}/health",
        f"{PREFIX}/delivery/quotes",
        f"{PREFIX}/delivery/shipments",
        f"{PREFIX}/delivery/shipments/{{id}}",
    }
    # The framework's schema-violation 422 is replaced by 400; a 422 that is
    # left is the carrier refusing a well-formed request, in the error envelope.
    for path in paths:
        for operation in schema["paths"][path].values():
            refusal = operation["responses"].get("422")
            if refusal is not None:
                assert refusal["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/ErrorResponse"
                }
