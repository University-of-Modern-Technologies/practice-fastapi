"""The HTTP contract of the auth endpoints.

The service is replaced by a double so that these tests are about the parts a
client can observe: status codes, envelope shapes and — above all — the cookie
attributes, which are what make refresh work in a browser at all.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from http.cookies import SimpleCookie
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.core.errors import UnauthorizedError
from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.router import create_auth_router
from app.modules.auth.schemas import AuthenticatedUser, PermissionOut
from app.modules.auth.types import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    REFRESH_TOKEN_TTL_SECONDS,
    AuthContext,
    AuthResult,
)

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000002")
ACCESS_TOKEN = "issued-access-token"

USER = AuthenticatedUser(
    id=USER_ID,
    email="morgan@example.com",
    name="Morgan Manager",
    roles=["manager"],
    permissions=[PermissionOut(resource="contacts", action="read", scope=PermissionScope.ALL)],
)


class FakeAuthService:
    """Answers exactly what the router asks, and records what it was given."""

    def __init__(self) -> None:
        self.logged_out: list[str | None] = []
        self.refreshed: list[str] = []
        self.authenticated: list[str] = []

    def _result(self, refresh_token: str) -> AuthResult:
        return AuthResult(
            user=USER,
            access_token=ACCESS_TOKEN,
            refresh_token=refresh_token,
            access_token_expires_in_seconds=ACCESS_TOKEN_TTL_SECONDS,
        )

    async def login(self, data: Any) -> AuthResult:  # noqa: ARG002
        return self._result(f"{SESSION_ID}.first-secret")

    async def refresh(self, refresh_token: str) -> AuthResult:
        self.refreshed.append(refresh_token)
        return self._result(f"{SESSION_ID}.rotated-secret")

    async def logout(self, refresh_token: str | None) -> None:
        self.logged_out.append(refresh_token)

    async def authenticate(self, access_token: str) -> AuthContext:
        self.authenticated.append(access_token)
        if access_token != ACCESS_TOKEN:
            raise UnauthorizedError()
        return AuthContext(user_id=USER_ID, session_id=SESSION_ID)

    async def me(self, user_id: uuid.UUID) -> AuthenticatedUser:  # noqa: ARG002
        return USER


@pytest.fixture
def auth_service() -> FakeAuthService:
    return FakeAuthService()


@pytest.fixture
def auth_app(settings: Settings, auth_service: FakeAuthService) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=[("/api/v1/auth", create_auth_router())])
    # The lifespan is what normally publishes this; these tests drive the
    # application through an in-process transport, which does not run it.
    app.state.settings = settings
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    return app


@pytest.fixture
async def auth_client(auth_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=auth_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def refresh_cookie(response: Response) -> SimpleCookie:
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        if REFRESH_COOKIE_NAME in cookie:
            return cookie
    message = "no refresh cookie was set"
    raise AssertionError(message)


async def test_login_answers_with_the_user_and_an_access_token(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "morgan@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accessToken"] == ACCESS_TOKEN
    assert data["accessTokenExpiresInSeconds"] == 900
    assert data["user"]["roles"] == ["manager"]
    assert data["user"]["permissions"] == [
        {"resource": "contacts", "action": "read", "scope": "ALL"}
    ]


async def test_the_refresh_token_never_appears_in_the_body(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "morgan@example.com", "password": "correct-horse"},
    )

    # It travels only as an http-only cookie, so a script on the page cannot
    # read it even if one is injected.
    assert "refresh" not in response.text.lower()


async def test_the_refresh_cookie_is_scoped_to_the_auth_endpoints(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "morgan@example.com", "password": "correct-horse"},
    )

    cookie = refresh_cookie(response)[REFRESH_COOKIE_NAME]
    assert cookie.value == f"{SESSION_ID}.first-secret"
    assert cookie["httponly"]
    assert cookie["samesite"].lower() == "lax"
    # A wider or narrower path makes the browser withhold the cookie from the
    # refresh call, which looks like a silently expiring session.
    assert cookie["path"] == REFRESH_COOKIE_PATH
    assert cookie["max-age"] == str(REFRESH_TOKEN_TTL_SECONDS)
    # Development runs over plain HTTP, where a secure cookie is dropped.
    assert not cookie["secure"]


async def test_a_short_password_is_a_400_not_a_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/auth/login", json={"email": "morgan@example.com", "password": "short"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_refresh_without_a_cookie_names_the_missing_token(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_REQUIRED"


async def test_refresh_rotates_the_cookie(
    auth_client: AsyncClient, auth_service: FakeAuthService
) -> None:
    presented = f"{SESSION_ID}.first-secret"
    auth_client.cookies.set(REFRESH_COOKIE_NAME, presented, path=REFRESH_COOKIE_PATH)

    response = await auth_client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert auth_service.refreshed == [presented]
    assert refresh_cookie(response)[REFRESH_COOKIE_NAME].value == f"{SESSION_ID}.rotated-secret"


async def test_logout_without_a_cookie_is_not_an_error(
    auth_client: AsyncClient, auth_service: FakeAuthService
) -> None:
    response = await auth_client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    assert auth_service.logged_out == [None]


async def test_logout_clears_the_cookie_on_the_same_path(auth_client: AsyncClient) -> None:
    auth_client.cookies.set(
        REFRESH_COOKIE_NAME, f"{SESSION_ID}.first-secret", path=REFRESH_COOKIE_PATH
    )

    response = await auth_client.post("/api/v1/auth/logout")

    cookie = refresh_cookie(response)[REFRESH_COOKIE_NAME]
    assert cookie.value == ""
    # A mismatched path would leave the old cookie in place.
    assert cookie["path"] == REFRESH_COOKIE_PATH


async def test_me_requires_a_bearer_token(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "authorization",
    ["", "Basic abc", "Bearer", f"Token {ACCESS_TOKEN}"],
    ids=["empty", "wrong-scheme", "no-credentials", "unsupported-scheme"],
)
async def test_an_unusable_authorization_header_is_unauthorized(
    auth_client: AsyncClient, authorization: str
) -> None:
    response = await auth_client.get("/api/v1/auth/me", headers={"authorization": authorization})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_me_returns_the_full_permission_list(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        "/api/v1/auth/me", headers={"authorization": f"Bearer {ACCESS_TOKEN}"}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(USER_ID)
    assert data["permissions"] == [{"resource": "contacts", "action": "read", "scope": "ALL"}]


async def test_a_rejected_token_answers_with_the_error_envelope(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get(
        "/api/v1/auth/me", headers={"authorization": "Bearer stale-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
