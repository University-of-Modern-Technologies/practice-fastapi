from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import structlog

from app.core.settings import Settings
from app.infra_profile import create_infra_stack
from app.modules.ai import MOCK_AI_PROVIDER_NAME

TEST_SECRET = "test-secret-value-that-is-long-enough"


def _settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://user:pass@localhost:5432/practice_crm_test?schema=public",
        jwt_access_secret=TEST_SECRET,
        jwt_refresh_secret=TEST_SECRET,
        redis_url="redis://localhost:6379",
        mongodb_url="mongodb://localhost:27017/practice_events_test",
        **overrides,
    )


class _FakeRedis:
    """Records whether it was ever actually touched."""

    key_prefix = ""

    def __init__(self) -> None:
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:  # noqa: ARG002
        self.get_calls += 1
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:  # noqa: ARG002
        self.set_calls += 1

    async def delete(self, *keys: str) -> None:
        pass

    async def scan_iter(self, match: str, count: int) -> AsyncIterator[str]:  # noqa: ARG002
        return
        yield  # pragma: no cover - makes this an async generator

    async def eval_script(self, script: str, keys: Any, args: Any) -> Any:  # noqa: ARG002
        return None

    async def ping(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _logger() -> structlog.stdlib.BoundLogger:
    # structlog's own stubs type get_logger() as returning Any.
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger("test"))


def test_defaults_to_the_live_profile_matching_the_pre_existing_behaviour() -> None:
    stack = create_infra_stack(_settings(), _FakeRedis(), _logger())

    assert stack.profile == "live"
    assert stack.ai_provider.name == MOCK_AI_PROVIDER_NAME


def test_forwards_configured_settings_when_live() -> None:
    stack = create_infra_stack(
        _settings(
            infra_profile="live",
            ai_endpoint_url="https://example.invalid/complete",
            delivery_base_url="https://example.invalid/delivery",
        ),
        _FakeRedis(),
        _logger(),
    )

    assert stack.ai_provider.name != MOCK_AI_PROVIDER_NAME


async def test_offline_forces_every_stand_in_even_with_real_settings_configured() -> None:
    redis = _FakeRedis()
    stack = create_infra_stack(
        _settings(
            infra_profile="offline",
            ai_endpoint_url="https://example.invalid/complete",
            delivery_base_url="https://example.invalid/delivery",
        ),
        redis,
        _logger(),
    )

    assert stack.profile == "offline"
    assert stack.ai_provider.name == MOCK_AI_PROVIDER_NAME

    # The cache never touches the Redis client it was handed.
    await stack.cache.set("some-key", "value")
    await stack.cache.get("some-key")
    assert redis.set_calls == 0
    assert redis.get_calls == 0


async def test_uses_the_real_cache_in_the_live_profile() -> None:
    redis = _FakeRedis()
    stack = create_infra_stack(
        _settings(infra_profile="live"),
        redis,
        _logger(),
    )

    await stack.cache.set("some-key", "value")
    assert redis.set_calls == 1


def test_offline_keeps_the_tuning_knobs_that_do_not_select_an_implementation() -> None:
    """Only the endpoint/base URL are withheld — the caps a service enforces stay."""
    stack = create_infra_stack(
        _settings(infra_profile="offline", ai_max_input_chars=1234, ai_cache_ttl_seconds=42),
        _FakeRedis(),
        _logger(),
    )

    assert stack.ai_config.max_input_chars == 1234
    assert stack.ai_config.cache_ttl_seconds == 42
    assert stack.ai_config.endpoint_url is None
