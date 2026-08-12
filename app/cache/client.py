"""Redis connectivity.

The driver is wrapped rather than used directly for two reasons: the cache
service must stay testable without a live server, and the key prefix has to be
applied in exactly one place. The wrapper exposes only the handful of commands
the application actually issues, so a test double is a dozen lines of plain
Python.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from redis.asyncio import Redis

from app.core.settings import Settings
from app.health.readiness import ReadinessCheck

# A command is abandoned instead of hanging: the cache layer falls back to the
# source of truth, so waiting is strictly worse than failing.
CONNECT_TIMEOUT_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 2.0
HEALTH_CHECK_INTERVAL_SECONDS = 30

CACHE_READINESS_CHECK_NAME = "cache"


class CacheRedis(Protocol):
    """The command surface the cache and the limiter depend on."""

    #: Prefix the wrapper prepends to every key it sends.
    key_prefix: str

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, *keys: str) -> None: ...

    def scan_iter(self, match: str, count: int) -> AsyncIterator[str]: ...

    async def eval_script(self, script: str, keys: Sequence[str], args: Sequence[str]) -> Any: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class PrefixedRedis:
    """Namespaces every key with the configured prefix.

    The prefix is applied to key arguments only. SCAN patterns are passed
    through untouched and replies are returned exactly as Redis sent them, which
    means a caller that scans must build the pattern with the prefix and strip
    it back off the results. That asymmetry is deliberate: it matches how key
    prefixing behaves across the drivers this project targets, so both backends
    can share one Redis instance and one set of keys.
    """

    def __init__(self, client: Redis, key_prefix: str) -> None:
        self._client = client
        self.key_prefix = key_prefix

    def _prefixed(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    async def get(self, key: str) -> str | None:
        value = await self._client.get(self._prefixed(key))
        return None if value is None else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(self._prefixed(key), value, ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        await self._client.delete(*(self._prefixed(key) for key in keys))

    async def scan_iter(self, match: str, count: int) -> AsyncIterator[str]:
        async for key in self._client.scan_iter(match=match, count=count):
            yield str(key)

    async def eval_script(self, script: str, keys: Sequence[str], args: Sequence[str]) -> Any:
        """Runs a Lua script. Keys are passed verbatim, without the prefix.

        Scripts address keys the application composes in full, so prefixing them
        again here would produce a second, unreachable namespace.
        """
        return await self._client.eval(script, len(keys), *keys, *args)

    async def ping(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()


def create_redis_client(settings: Settings) -> PrefixedRedis:
    """Opens a lazily-connecting client bound to the configured prefix."""
    client: Redis = Redis.from_url(
        settings.redis_url,
        # Values are JSON text, so decoding once in the driver saves every call
        # site from doing it.
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=COMMAND_TIMEOUT_SECONDS,
        health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
    )
    return PrefixedRedis(client, settings.redis_key_prefix)


async def close_redis_client(client: CacheRedis) -> None:
    """Closes the connection pool, tolerating a server that is already gone."""
    try:
        await client.close()
    except Exception:  # shutdown must not fail because the cache is unreachable
        return


def create_cache_readiness_check(client: CacheRedis) -> ReadinessCheck:
    """Probe for ``/health/ready``.

    Marked non-critical on purpose: a cache outage costs latency, not
    correctness, and must never pull the instance out of the load balancer.
    """

    async def check() -> None:
        await client.ping()

    return ReadinessCheck(name=CACHE_READINESS_CHECK_NAME, check=check, critical=False)
