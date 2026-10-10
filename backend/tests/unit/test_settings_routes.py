"""Who may read and write the organization's settings.

Settings belong to the whole organization, so there is no record of the
caller's own that an ``OWN`` grant could be narrowed to. Reading and writing both
need the grant at ``ALL``; the sibling backend refuses a narrower one with the
same 403.
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
from app.modules.auth.dependencies import get_auth
from app.modules.auth.types import AuthContext
from app.modules.rbac.dependencies import get_rbac_service
from app.modules.settings.router import create_settings_router, get_settings_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000002")
KEY = "organization.name"


class FakeRbac:
    def __init__(self) -> None:
        self.scope: PermissionScope | None = PermissionScope.ALL

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope | None:
        del user_id, resource, action
        return self.scope


class RecordingSettings:
    def __init__(self) -> None:
        self.writes: list[str] = []

    async def upsert(self, access: Any, key: str, payload: Any) -> dict[str, Any]:
        del access, payload
        self.writes.append(f"upsert:{key}")
        return {
            "key": key,
            "value": "Acme",
            "description": "Organization name",
            "source": "database",
            "updatedById": None,
            "updatedAt": None,
        }

    async def remove(self, access: Any, key: str) -> None:
        del access
        self.writes.append(f"remove:{key}")

    async def list(self) -> list[dict[str, Any]]:
        self.writes.append("list")
        return []

    async def get_by_key(self, key: str) -> dict[str, Any]:
        self.writes.append(f"get:{key}")
        return {
            "key": key,
            "value": "Acme",
            "description": "Organization name",
            "source": "database",
            "updatedById": None,
            "updatedAt": None,
        }


@pytest.fixture
def rbac() -> FakeRbac:
    return FakeRbac()


@pytest.fixture
def service() -> RecordingSettings:
    return RecordingSettings()


@pytest.fixture
async def client(
    settings: Settings, rbac: FakeRbac, service: RecordingSettings
) -> AsyncIterator[AsyncClient]:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app: FastAPI = create_app(settings, routers=[("/api/v1/settings", create_settings_router())])
    app.state.settings = settings
    app.dependency_overrides[get_auth] = lambda: AuthContext(user_id=USER_ID, session_id=SESSION_ID)
    app.dependency_overrides[get_rbac_service] = lambda: rbac
    app.dependency_overrides[get_settings_service] = lambda: service
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


async def test_a_write_with_an_own_grant_is_refused(
    client: AsyncClient, rbac: FakeRbac, service: RecordingSettings
) -> None:
    rbac.scope = PermissionScope.OWN

    response = await client.put(f"/api/v1/settings/{KEY}", json={"value": "Acme"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert service.writes == []


async def test_a_reset_with_an_own_grant_is_refused(
    client: AsyncClient, rbac: FakeRbac, service: RecordingSettings
) -> None:
    rbac.scope = PermissionScope.OWN

    response = await client.delete(f"/api/v1/settings/{KEY}")

    assert response.status_code == 403
    assert service.writes == []


async def test_a_write_with_an_all_grant_is_accepted(
    client: AsyncClient, service: RecordingSettings
) -> None:
    response = await client.put(f"/api/v1/settings/{KEY}", json={"value": "Acme"})

    assert response.status_code == 200
    assert service.writes == [f"upsert:{KEY}"]


@pytest.mark.parametrize("path", ["/api/v1/settings", f"/api/v1/settings/{KEY}"])
async def test_a_read_with_an_own_grant_is_refused(
    client: AsyncClient, rbac: FakeRbac, service: RecordingSettings, path: str
) -> None:
    rbac.scope = PermissionScope.OWN

    response = await client.get(path)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert service.writes == []


@pytest.mark.parametrize("path", ["/api/v1/settings", f"/api/v1/settings/{KEY}"])
async def test_a_read_with_an_all_grant_is_accepted(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 200
