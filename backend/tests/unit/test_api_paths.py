"""Everything the service exposes lives under `/api`.

One proxy rule in front of the backend has to route all of it, so a path that
slips back out of the prefix silently disappears behind the proxy.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_the_schema_is_published_under_the_api_prefix(client: AsyncClient) -> None:
    response = await client.get("/api/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Practice CRM API"


async def test_the_docs_load_the_schema_from_under_the_api_prefix(client: AsyncClient) -> None:
    response = await client.get("/api/docs")

    assert response.status_code == 200
    assert "'/api/openapi.json'" in response.text
    assert "'/api/docs/oauth2-redirect'" in response.text


async def test_the_docs_are_exempt_from_the_content_policy(client: AsyncClient) -> None:
    for path in ("/api/docs", "/api/docs/oauth2-redirect"):
        response = await client.get(path)

        assert response.status_code == 200
        assert "content-security-policy" not in response.headers


@pytest.mark.parametrize(
    "path",
    ["/docs", "/docs/oauth2-redirect", "/openapi.json", "/health/live", "/health/ready"],
)
async def test_nothing_is_left_outside_the_api_prefix(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 404
