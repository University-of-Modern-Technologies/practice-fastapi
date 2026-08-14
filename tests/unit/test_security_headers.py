"""Response hardening: the CSP, and what CORS is allowed to advertise."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.settings import Settings
from app.middleware.security_headers import CONTENT_SECURITY_POLICY


def _directives(policy: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in policy.split(";"):
        name, _, value = item.strip().partition(" ")
        if name:
            parsed[name] = value
    return parsed


async def test_the_policy_blocks_inline_event_handlers(client: AsyncClient) -> None:
    """`script-src 'self'` alone still permits an inline `onclick=`."""
    policy = (await client.get("/health/live")).headers["content-security-policy"]

    assert _directives(policy)["script-src-attr"] == "'none'"


async def test_the_policy_is_serialised_without_padding(client: AsyncClient) -> None:
    """Directives are joined by a bare `;`, so the header can be diffed as-is."""
    policy = (await client.get("/health/live")).headers["content-security-policy"]

    assert policy == CONTENT_SECURITY_POLICY
    assert "; " not in policy


async def test_the_policy_keeps_its_baseline_directives(client: AsyncClient) -> None:
    policy = _directives((await client.get("/health/live")).headers["content-security-policy"])

    assert policy["default-src"] == "'self'"
    assert policy["object-src"] == "'none'"
    assert policy["frame-ancestors"] == "'self'"
    assert "upgrade-insecure-requests" in policy


async def test_cors_advertises_no_extra_readable_headers(
    settings: Settings, client: AsyncClient
) -> None:
    """Nothing beyond the CORS-safelisted set is exposed to a cross-origin script."""
    origin = settings.cors_origins[0]
    response = await client.get("/health/live", headers={"origin": origin})

    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-expose-headers" not in response.headers
