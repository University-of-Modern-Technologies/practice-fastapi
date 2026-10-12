"""The order in which a user route refuses a request.

Authentication comes first, then whether the caller holds the permission at any
breadth, then the shape of the request, and only then the breadth itself, which
may depend on the validated input. The sibling backend refuses in the same
order, so the same bad request gets the same status from either one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import ConflictError
from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.auth.dependencies import get_auth
from app.modules.auth.types import AuthContext
from app.modules.rbac.dependencies import get_rbac_service
from app.modules.rbac.types import Actor
from app.modules.users.router import create_users_router, get_users_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
OTHER_ID = uuid.UUID("10000000-0000-4000-8000-000000000003")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000002")


class FakeRbac:
    def __init__(self) -> None:
        self.scope: PermissionScope | None = PermissionScope.ALL

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope | None:
        del user_id, resource, action
        return self.scope


class RecordingUsers:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def disable(self, actor: Actor, user_id: uuid.UUID) -> None:
        self.calls.append(("disable", (actor, user_id)))
        raise ConflictError("You cannot disable your own account", "CANNOT_DISABLE_SELF")


@pytest.fixture
def rbac() -> FakeRbac:
    return FakeRbac()


@pytest.fixture
def users() -> RecordingUsers:
    return RecordingUsers()


@pytest.fixture
async def client(
    settings: Settings, rbac: FakeRbac, users: RecordingUsers
) -> AsyncIterator[AsyncClient]:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app: FastAPI = create_app(settings, routers=[("/api/v1/users", create_users_router())])
    app.state.settings = settings
    app.dependency_overrides[get_auth] = lambda: AuthContext(user_id=USER_ID, session_id=SESSION_ID)
    app.dependency_overrides[get_rbac_service] = lambda: rbac
    app.dependency_overrides[get_users_service] = lambda: users
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# A caller without the permission learns nothing about the body.
async def test_a_missing_permission_is_refused_before_the_body_is_validated(
    client: AsyncClient, rbac: FakeRbac
) -> None:
    rbac.scope = None

    response = await client.post("/api/v1/users", json={"email": "not-an-address"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_a_held_permission_lets_validation_answer_first(
    client: AsyncClient, rbac: FakeRbac
) -> None:
    rbac.scope = PermissionScope.OWN

    response = await client.get("/api/v1/users/not-a-uuid")

    # The breadth is applied to the validated identifier, so a malformed one is
    # a 400 even for a caller whose grant would not cover a well-formed one.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_the_breadth_is_applied_after_validation(client: AsyncClient, rbac: FakeRbac) -> None:
    rbac.scope = PermissionScope.OWN

    response = await client.get(f"/api/v1/users/{OTHER_ID}")

    assert response.status_code == 403


# The refusal reaches the client in the standard envelope.
async def test_disabling_yourself_answers_409_with_its_own_code(
    client: AsyncClient, users: RecordingUsers
) -> None:
    response = await client.post(f"/api/v1/users/{USER_ID}/disable")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANNOT_DISABLE_SELF"
    [(_, (actor, user_id))] = users.calls
    assert actor.actor_id == USER_ID
    assert user_id == USER_ID
