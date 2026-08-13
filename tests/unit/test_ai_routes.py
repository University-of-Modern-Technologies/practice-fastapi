"""The HTTP contract of the assistant endpoints.

RBAC and authentication are replaced by doubles so that these tests are about
what a client can observe: paths, status codes, the ``data`` envelope, and the
fact that a schema violation is a 400 with our error code rather than the
framework's 422.
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
from app.modules.ai.mock_provider import create_mock_ai_provider
from app.modules.ai.router import create_ai_router, get_ai_service
from app.modules.ai.service import AiService
from app.modules.ai.types import DEFAULT_AI_MAX_INPUT_CHARS
from app.modules.auth.dependencies import get_auth, get_auth_service
from app.modules.auth.types import AuthContext
from app.modules.rbac.dependencies import get_rbac_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000002")
DEAL_ID = "5ff875e1-4c1d-4e45-9c8a-fceb5fb5d836"

DEAL_BODY: dict[str, Any] = {
    "id": DEAL_ID,
    "title": "Warehouse automation",
    "stage": "PROPOSAL",
}


class FakeRbacService:
    """Grants — or withholds — exactly one permission."""

    def __init__(self, scope: PermissionScope | None = PermissionScope.ALL) -> None:
        self.scope = scope
        self.asked: list[tuple[str, str]] = []

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope | None:
        del user_id
        self.asked.append((resource, action))
        return self.scope


@pytest.fixture
def rbac() -> FakeRbacService:
    return FakeRbacService()


@pytest.fixture
def ai_app(settings: Settings, rbac: FakeRbacService) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=[("/api/v1/ai", create_ai_router())])
    app.state.settings = settings

    async def authenticated() -> AuthContext:
        return AuthContext(user_id=USER_ID, session_id=SESSION_ID)

    app.dependency_overrides[get_auth] = authenticated
    app.dependency_overrides[get_rbac_service] = lambda: rbac
    # The offline provider keeps the route tests deterministic and socket-free.
    app.dependency_overrides[get_ai_service] = lambda: AiService(create_mock_ai_provider())
    return app


@pytest.fixture
async def ai_client(ai_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=ai_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_summaries_answer_at_the_documented_path(ai_client: AsyncClient) -> None:
    response = await ai_client.post("/api/v1/ai/summaries/deal", json=DEAL_BODY)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dealId"] == DEAL_ID
    assert data["provider"] == "mock"
    assert data["cached"] is False
    assert "Warehouse automation" in data["summary"]


async def test_classification_answers_at_the_documented_path(ai_client: AsyncClient) -> None:
    response = await ai_client.post(
        "/api/v1/ai/classify/inquiry", json={"text": "Where is my parcel?"}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["category"] == "shipping"
    assert data["provider"] == "mock"


async def test_every_success_is_wrapped_in_the_data_envelope(ai_client: AsyncClient) -> None:
    response = await ai_client.post("/api/v1/ai/classify/inquiry", json={"text": "Hello"})

    assert set(response.json()) == {"data"}


async def test_oversized_inquiry_text_is_a_400_before_the_service_runs(
    ai_client: AsyncClient,
) -> None:
    response = await ai_client.post(
        "/api/v1/ai/classify/inquiry", json={"text": "x" * (DEFAULT_AI_MAX_INPUT_CHARS + 1)}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_a_malformed_deal_identifier_is_a_400(ai_client: AsyncClient) -> None:
    response = await ai_client.post(
        "/api/v1/ai/summaries/deal", json={**DEAL_BODY, "id": "not-a-uuid"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_unknown_body_fields_are_dropped_rather_than_refused(
    ai_client: AsyncClient,
) -> None:
    response = await ai_client.post(
        "/api/v1/ai/summaries/deal",
        json={**DEAL_BODY, "passwordHash": "$2b$10$superSecretHashValue"},
    )

    assert response.status_code == 200
    assert "superSecretHashValue" not in response.text


async def test_the_permission_checked_is_ai_use(
    ai_client: AsyncClient, rbac: FakeRbacService
) -> None:
    await ai_client.post("/api/v1/ai/classify/inquiry", json={"text": "Hello"})

    assert rbac.asked == [("ai", "use")]


async def test_a_caller_without_the_permission_is_forbidden(
    ai_client: AsyncClient, rbac: FakeRbacService
) -> None:
    rbac.scope = None

    response = await ai_client.post("/api/v1/ai/classify/inquiry", json={"text": "Hello"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_a_caller_holding_only_own_may_still_use_the_assistant(
    ai_client: AsyncClient, rbac: FakeRbacService
) -> None:
    rbac.scope = PermissionScope.OWN

    response = await ai_client.post("/api/v1/ai/classify/inquiry", json={"text": "Hello"})

    # Nothing here selects rows, so the narrower grant has nothing to narrow.
    assert response.status_code == 200


async def test_an_anonymous_caller_is_unauthorized(ai_app: FastAPI) -> None:
    # The real resolver runs, but against a service double: no bearer header
    # means it never gets that far, and that is exactly what is asserted.
    ai_app.dependency_overrides.pop(get_auth)
    ai_app.dependency_overrides[get_auth_service] = lambda: None

    transport = ASGITransport(app=ai_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/ai/classify/inquiry", json={"text": "Hello"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_the_schema_never_advertises_a_422(ai_app: FastAPI) -> None:
    paths = {path: item for path, item in ai_app.openapi()["paths"].items() if "/ai/" in path}

    assert set(paths) == {"/api/v1/ai/summaries/deal", "/api/v1/ai/classify/inquiry"}
    for operations in paths.values():
        for operation in operations.values():
            assert "422" not in operation["responses"]
