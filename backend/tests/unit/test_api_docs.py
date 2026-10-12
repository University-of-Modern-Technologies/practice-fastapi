"""The interactive docs: switched by configuration and served without a CDN."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.api_docs import SWAGGER_UI_ASSETS
from app.core.settings import Settings
from app.factory import create_app

TEST_SECRET = "test-secret-value-that-is-long-enough"
DOCS_PATHS = [
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/openapi.json",
    *(f"/api/docs/{name}" for name in SWAGGER_UI_ASSETS),
]


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": "postgresql://user:pass@localhost:5432/practice_crm_test",
        "jwt_access_secret": TEST_SECRET,
        "jwt_refresh_secret": TEST_SECRET,
        "redis_url": "redis://localhost:6379",
        "mongodb_url": "mongodb://localhost:27017/practice_events_test",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [("development", True), ("test", True), ("production", False)],
)
def test_the_docs_default_to_on_everywhere_but_production(app_env: str, expected: bool) -> None:
    assert _settings(app_env=app_env).api_docs_enabled is expected


@pytest.mark.parametrize(
    ("app_env", "written", "expected"),
    [
        ("production", "true", True),
        ("development", "false", False),
        ("production", "", False),
        ("development", "", True),
    ],
)
def test_the_environment_overrides_the_default(
    monkeypatch: pytest.MonkeyPatch, app_env: str, written: str, expected: bool
) -> None:
    """A blank value, as `.env.example` ships it, keeps the default."""
    monkeypatch.setenv("API_DOCS_ENABLED", written)

    assert _settings(app_env=app_env).api_docs_enabled is expected


async def _client(settings: Settings, root_path: str = "") -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(
        app=create_app(settings), raise_app_exceptions=False, root_path=root_path
    )
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def enabled_client() -> AsyncIterator[AsyncClient]:
    async for client in _client(_settings(api_docs_enabled=True)):
        yield client


@pytest.fixture
async def disabled_client() -> AsyncIterator[AsyncClient]:
    async for client in _client(_settings(api_docs_enabled=False)):
        yield client


async def test_the_page_loads_nothing_from_another_origin(enabled_client: AsyncClient) -> None:
    response = await enabled_client.get("/api/docs")
    sources = re.findall(r'(?:src|href)="([^"]+)"', response.text)

    assert response.status_code == 200
    assert sorted(sources) == sorted(f"/api/docs/{name}" for name in SWAGGER_UI_ASSETS)
    assert "://" not in "".join(sources)


@pytest.mark.parametrize(("name", "media_type"), list(SWAGGER_UI_ASSETS.items()))
async def test_every_asset_is_served_locally(
    enabled_client: AsyncClient, name: str, media_type: str
) -> None:
    response = await enabled_client.get(f"/api/docs/{name}")

    assert response.status_code == 200
    # `nosniff` is set on every response, so a wrong type would stop the page.
    assert response.headers["content-type"] == media_type
    assert len(response.content) > 0


async def test_the_bundle_understands_openapi_3_1(enabled_client: AsyncClient) -> None:
    """Swagger UI reads 3.1 documents from major version 5 on."""
    response = await enabled_client.get("/api/docs/swagger-ui-bundle.js")
    version = re.search(r'PACKAGE_VERSION:"(\d+)\.\d+\.\d+"', response.text)

    assert version is not None
    assert int(version.group(1)) >= 5


async def test_the_page_honours_a_proxy_prefix() -> None:
    async for client in _client(_settings(), root_path="/crm"):
        response = await client.get("/crm/api/docs")

        assert response.status_code == 200
        assert "'/crm/api/openapi.json'" in response.text
        assert 'src="/crm/api/docs/swagger-ui-bundle.js"' in response.text


@pytest.mark.parametrize("path", DOCS_PATHS)
async def test_switched_off_nothing_is_served(disabled_client: AsyncClient, path: str) -> None:
    response = await disabled_client.get(path)

    assert response.status_code == 404


async def test_switched_off_the_api_itself_still_answers(disabled_client: AsyncClient) -> None:
    response = await disabled_client.get("/api/health/live")

    assert response.status_code == 200
