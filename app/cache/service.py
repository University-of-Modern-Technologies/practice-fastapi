"""Cache facade.

Every method here is fail-open. A read error is logged and reported as a miss, a
write error is logged and dropped. That rule is what lets call sites treat the
cache as an optimisation instead of a dependency: the worst outcome of a broken
Redis is a slower request, never a wrong or failed one.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.cache.client import CacheRedis
from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger("cache")

#: SCAN cursor size. Large enough to keep round trips down, small enough that a
#: single reply never pins an unbounded slice of the keyspace in memory.
SCAN_BATCH_SIZE = 200


class CacheService:
    """JSON value cache over a narrow Redis command surface."""

    def __init__(self, redis: CacheRedis, settings: Settings) -> None:
        self._redis = redis
        self._default_ttl_seconds = settings.cache_ttl_seconds

    def _strip_key_prefix(self, key: str) -> str:
        prefix = self._redis.key_prefix
        return key[len(prefix) :] if key.startswith(prefix) else key

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
        except Exception as error:
            # Fail open: an unreachable cache must never break a request.
            logger.warning(
                "Cache read failed, falling back to the source", key=key, err=repr(error)
            )
            return None

        if raw is None:
            return None

        try:
            return json.loads(raw)
        except ValueError as error:
            # A value that cannot be parsed can never become useful, so it is
            # removed rather than left to fail on every future read.
            logger.warning("Discarding corrupt cache entry", key=key, err=repr(error))
            await self.delete(key)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        try:
            encoded = json.dumps(value, default=str)
        except (TypeError, ValueError) as error:
            logger.warning("Refusing to cache a non-serialisable value", key=key, err=repr(error))
            return

        try:
            await self._redis.set(key, encoded, ttl_seconds or self._default_ttl_seconds)
        except Exception as error:
            logger.warning("Cache write failed", key=key, err=repr(error))

    async def remember[T](
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        """Returns the cached value, otherwise loads it and stores it."""
        cached = await self.get(key)
        if cached is not None:
            # The cast is unavoidable: what comes back from Redis is JSON, and
            # only the caller knows which shape it asked to be stored.
            return cached  # type: ignore[no-any-return]

        value = await loader()
        await self.set(key, value, ttl_seconds)
        return value

    async def delete(self, keys: str | Sequence[str]) -> None:
        targets = [keys] if isinstance(keys, str) else list(keys)
        if not targets:
            return
        try:
            await self._redis.delete(*targets)
        except Exception as error:
            logger.warning("Cache delete failed", count=len(targets), err=repr(error))

    async def invalidate_prefix(self, prefix: str) -> None:
        """Drops every key in a namespace.

        SCAN is used instead of KEYS so that a large keyspace is walked in
        batches rather than blocking the server for the length of one command.
        """
        batch: list[str] = []
        try:
            pattern = f"{self._redis.key_prefix}{prefix}*"
            async for key in self._redis.scan_iter(pattern, SCAN_BATCH_SIZE):
                batch.append(self._strip_key_prefix(key))
                if len(batch) >= SCAN_BATCH_SIZE:
                    await self.delete(batch)
                    batch.clear()
            if batch:
                await self.delete(batch)
        except Exception as error:
            logger.warning("Cache prefix invalidation failed", prefix=prefix, err=repr(error))


class NoopCacheService:
    """Cache that stores nothing.

    Used by call sites constructed without infrastructure — unit tests, offline
    tooling — so they need no branch for "the cache is absent".
    """

    async def get(self, key: str) -> Any | None:  # noqa: ARG002
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Intentionally empty: nothing is stored."""

    async def remember[T](
        self,
        key: str,  # noqa: ARG002
        ttl_seconds: int,  # noqa: ARG002
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        return await loader()

    async def delete(self, keys: str | Sequence[str]) -> None:
        """Intentionally empty: nothing is stored."""

    async def invalidate_prefix(self, prefix: str) -> None:
        """Intentionally empty: nothing is stored."""
