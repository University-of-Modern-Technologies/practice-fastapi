"""The Redis client fails fast: an unreachable cache must cost a request little."""

from __future__ import annotations

from app.cache.client import (
    COMMAND_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    create_redis_client,
)
from app.core.settings import Settings


async def test_every_command_is_bounded_by_a_short_timeout(settings: Settings) -> None:
    client = create_redis_client(settings)
    kwargs = client._client.connection_pool.connection_kwargs

    assert COMMAND_TIMEOUT_SECONDS == 2.0
    assert kwargs["socket_timeout"] == COMMAND_TIMEOUT_SECONDS
    assert kwargs["socket_connect_timeout"] == CONNECT_TIMEOUT_SECONDS
    await client.close()


async def test_a_failed_command_is_not_retried(settings: Settings) -> None:
    """A retry loop is a queue by another name: during an outage it is exactly
    what holds a request for tens of seconds before the cache gives up."""
    client = create_redis_client(settings)
    connection = client._client.connection_pool.make_connection()  # type: ignore[no-untyped-call]

    assert connection.retry.get_retries() == 0
    await client.close()
