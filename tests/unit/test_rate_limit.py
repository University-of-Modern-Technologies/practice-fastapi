"""Rate limiting, driven through the real ASGI stack with a scripted Redis."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.types import Receive, Scope, Send

from app.core.security import create_access_token
from app.core.settings import Settings
from app.middleware.rate_limit import (
    AUTH_RATE_LIMIT_NAMESPACE,
    RATE_LIMIT_ERROR_CODE,
    RATE_LIMIT_NAMESPACE,
    RateLimitMiddleware,
    client_identity,
)

WINDOW_MS = 60_000


class ScriptedRedis:
    """Replays a fixed verdict and records what the middleware asked for."""

    def __init__(self, verdicts: list[list[int]]) -> None:
        self._verdicts = verdicts
        self.keys: list[str] = []
        self.args: list[Sequence[str]] = []

    async def eval_script(self, script: str, keys: Sequence[str], args: Sequence[str]) -> Any:  # noqa: ARG002
        self.keys.append(keys[0])
        self.args.append(args)
        return self._verdicts.pop(0) if self._verdicts else [1, 0, WINDOW_MS]


class BrokenRedis:
    async def eval_script(self, script: str, keys: Sequence[str], args: Sequence[str]) -> Any:  # noqa: ARG002
        raise ConnectionError(keys)


async def _endpoint(scope: Scope, receive: Receive, send: Send) -> None:  # noqa: ARG001
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b'{"status":"ok"}'})


def _client(redis: Any, settings: Settings) -> AsyncClient:
    app = RateLimitMiddleware(_endpoint, redis=redis, settings=settings)
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


@pytest.fixture
def limited_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"rate_limit_max_requests": 5, "auth_rate_limit_max_requests": 2}
    )


async def test_an_allowed_request_carries_the_budget_headers(limited_settings: Settings) -> None:
    """The draft-7 pair, and nothing from the superseded `x-ratelimit-*` family."""
    async with _client(ScriptedRedis([[1, 4, WINDOW_MS]]), limited_settings) as client:
        response = await client.get("/api/v1/contacts")

    assert response.status_code == 200
    assert response.headers["ratelimit-policy"] == "5;w=60"
    assert response.headers["ratelimit"] == "limit=5, remaining=4, reset=60"
    assert "x-ratelimit-limit" not in response.headers


async def test_reset_counts_down_rather_than_repeating_the_window(
    limited_settings: Settings,
) -> None:
    """`reset` is the seconds still to run, not the width of the window."""
    async with _client(ScriptedRedis([[1, 4, 12_000]]), limited_settings) as client:
        response = await client.get("/api/v1/contacts")

    assert response.headers["ratelimit"] == "limit=5, remaining=4, reset=12"


async def test_an_exceeded_budget_answers_429_in_the_error_envelope(
    limited_settings: Settings,
) -> None:
    async with _client(ScriptedRedis([[0, 0, 30_000]]), limited_settings) as client:
        response = await client.get("/api/v1/contacts")

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == RATE_LIMIT_ERROR_CODE
    assert body["error"]["message"]
    assert "requestId" in body


async def test_a_rejected_request_says_when_to_retry(limited_settings: Settings) -> None:
    async with _client(ScriptedRedis([[0, 0, 30_000]]), limited_settings) as client:
        response = await client.get("/api/v1/contacts")

    assert response.headers["retry-after"] == "30"
    assert response.headers["ratelimit-policy"] == "5;w=60"
    assert response.headers["ratelimit"] == "limit=5, remaining=0, reset=30"


async def test_authentication_paths_spend_both_budgets(limited_settings: Settings) -> None:
    """`/auth` is charged the global budget *and* its own stricter one."""
    redis = ScriptedRedis([[1, 4, WINDOW_MS], [1, 1, WINDOW_MS]])

    async with _client(redis, limited_settings) as client:
        response = await client.post("/api/v1/auth/login")

    prefix = limited_settings.redis_key_prefix
    assert redis.keys[0].startswith(f"{prefix}{RATE_LIMIT_NAMESPACE}")
    assert redis.keys[1].startswith(f"{prefix}{AUTH_RATE_LIMIT_NAMESPACE}")
    assert [args[2] for args in redis.args] == ["5", "2"]
    # The narrower budget is the one reported back.
    assert response.headers["ratelimit-policy"] == "2;w=60"
    assert response.headers["ratelimit"] == "limit=2, remaining=1, reset=60"


async def test_an_exhausted_global_budget_leaves_the_auth_budget_unspent(
    limited_settings: Settings,
) -> None:
    """A request that is not going to be served must not be charged twice."""
    redis = ScriptedRedis([[0, 0, 30_000]])

    async with _client(redis, limited_settings) as client:
        response = await client.post("/api/v1/auth/login")

    assert response.status_code == 429
    assert len(redis.keys) == 1
    assert redis.keys[0].startswith(f"{limited_settings.redis_key_prefix}{RATE_LIMIT_NAMESPACE}")
    assert response.headers["ratelimit"] == "limit=5, remaining=0, reset=30"


def _bearer(settings: Settings, subject: str) -> dict[str, str]:
    token = create_access_token(
        subject=subject,
        session_id="6f1a0d2c-0f1a-4c1a-9c1a-0f1a4c1a9c1a",
        secret=settings.jwt_access_secret,
        ttl_seconds=300,
    )
    return {"authorization": f"Bearer {token}"}


async def test_a_signed_in_caller_gets_a_budget_of_its_own(limited_settings: Settings) -> None:
    """Behind NAT an address is shared; the account is not."""
    redis = ScriptedRedis([[1, 4, WINDOW_MS], [1, 4, WINDOW_MS]])
    first, second = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"

    async with _client(redis, limited_settings) as client:
        await client.get("/api/v1/contacts", headers=_bearer(limited_settings, first))
        await client.get("/api/v1/contacts", headers=_bearer(limited_settings, second))

    assert redis.keys[0].endswith(f"user:{first}")
    assert redis.keys[1].endswith(f"user:{second}")


@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-token",
        "Bearer",
        "Basic dXNlcjpwYXNz",
        "",
    ],
)
async def test_an_unusable_token_falls_back_to_the_address(
    limited_settings: Settings, header: str
) -> None:
    """The limiter never answers 401: authentication is somebody else's job."""
    redis = ScriptedRedis([[1, 4, WINDOW_MS]])

    async with _client(redis, limited_settings) as client:
        response = await client.get("/api/v1/contacts", headers={"authorization": header})

    assert response.status_code == 200
    assert redis.keys[0].endswith("127.0.0.1")


async def test_a_token_signed_with_another_secret_falls_back_to_the_address(
    limited_settings: Settings,
) -> None:
    foreign = create_access_token(
        subject="33333333-3333-4333-8333-333333333333",
        session_id="6f1a0d2c-0f1a-4c1a-9c1a-0f1a4c1a9c1a",
        secret="a-different-secret-of-at-least-32-chars",
        ttl_seconds=300,
    )
    redis = ScriptedRedis([[1, 4, WINDOW_MS]])

    async with _client(redis, limited_settings) as client:
        response = await client.get(
            "/api/v1/contacts", headers={"authorization": f"Bearer {foreign}"}
        )

    assert response.status_code == 200
    assert redis.keys[0].endswith("127.0.0.1")


async def test_ordinary_paths_use_the_general_namespace(limited_settings: Settings) -> None:
    redis = ScriptedRedis([[1, 4, WINDOW_MS]])

    async with _client(redis, limited_settings) as client:
        await client.get("/api/v1/contacts")

    assert redis.keys[0].startswith(f"{limited_settings.redis_key_prefix}{RATE_LIMIT_NAMESPACE}")
    assert AUTH_RATE_LIMIT_NAMESPACE not in redis.keys[0]


async def test_the_window_is_taken_from_configuration(limited_settings: Settings) -> None:
    redis = ScriptedRedis([[1, 4, WINDOW_MS]])

    async with _client(redis, limited_settings) as client:
        await client.get("/api/v1/contacts")

    assert redis.args[0][1] == str(limited_settings.rate_limit_window_seconds * 1_000)


async def test_an_unreachable_redis_lets_the_request_through(limited_settings: Settings) -> None:
    # The limiter guards against load. A Redis outage is load, so refusing
    # traffic here would turn a cache incident into an API outage.
    async with _client(BrokenRedis(), limited_settings) as client:
        response = await client.get("/api/v1/contacts")

    assert response.status_code == 200
    assert "x-ratelimit-limit" not in response.headers


async def test_non_http_traffic_is_passed_through(limited_settings: Settings) -> None:
    seen: list[str] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:  # noqa: ARG001
        seen.append(scope["type"])

    middleware = RateLimitMiddleware(downstream, redis=ScriptedRedis([]), settings=limited_settings)

    async def receive() -> Any:  # pragma: no cover - never called
        return {}

    async def send(message: Any) -> None:  # noqa: ARG001  # pragma: no cover - never called
        return None

    await middleware({"type": "lifespan"}, receive, send)

    assert seen == ["lifespan"]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        # A single client is normally handed a whole /64, so the budget follows
        # the subnet rather than an address it can rotate at will.
        ("2001:db8::1", "2001:db8::/64"),
        ("not-an-address", "not-an-address"),
    ],
)
def test_the_budget_follows_the_caller(host: str, expected: str) -> None:
    assert client_identity({"type": "http", "client": (host, 51_000)}) == expected


def test_an_unknown_peer_shares_one_budget() -> None:
    assert client_identity({"type": "http", "client": None}) == "unknown"
