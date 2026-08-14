"""Cache facade behaviour, driven against an in-memory Redis double."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from fnmatch import fnmatchcase
from typing import Any

import pytest

from app.cache.service import CacheService, NoopCacheService
from app.core.settings import Settings

KEY_PREFIX = "crm:"


class FakeRedis:
    """Dictionary-backed stand-in with the prefix semantics of the real client."""

    def __init__(self, key_prefix: str = KEY_PREFIX) -> None:
        self.key_prefix = key_prefix
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[tuple[str, ...]] = []
        self.scan_patterns: list[str] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(f"{self.key_prefix}{key}")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[f"{self.key_prefix}{key}"] = value
        self.ttls[f"{self.key_prefix}{key}"] = ttl_seconds

    async def delete(self, *keys: str) -> None:
        self.deleted.append(keys)
        for key in keys:
            self.store.pop(f"{self.key_prefix}{key}", None)

    async def scan_iter(self, match: str, count: int) -> AsyncIterator[str]:  # noqa: ARG002
        # Patterns are matched against the stored key, prefix included, and the
        # reply keeps the prefix — exactly what the real client does.
        self.scan_patterns.append(match)
        for key in list(self.store):
            if fnmatchcase(key, match):
                yield key

    async def eval_script(self, script: str, keys: Any, args: Any) -> Any:
        raise NotImplementedError

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class BrokenRedis(FakeRedis):
    """Every command fails, the way an unreachable server behaves."""

    async def get(self, key: str) -> str | None:
        raise ConnectionError(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:  # noqa: ARG002
        raise ConnectionError(key)

    async def delete(self, *keys: str) -> None:
        raise ConnectionError(keys)

    def scan_iter(self, match: str, count: int) -> AsyncIterator[str]:  # noqa: ARG002
        # Not a generator: the failure surfaces on the call, which is where an
        # unreachable server would refuse the connection.
        raise ConnectionError(match)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def cache(redis: FakeRedis, settings: Settings) -> CacheService:
    return CacheService(redis, settings)


async def test_get_returns_none_for_a_missing_key(cache: CacheService) -> None:
    assert await cache.get("absent") is None


async def test_set_then_get_round_trips_the_value(cache: CacheService) -> None:
    await cache.set("user:1", {"id": 1, "roles": ["admin"]})

    assert await cache.get("user:1") == {"id": 1, "roles": ["admin"]}


async def test_set_applies_the_configured_default_ttl(
    cache: CacheService,
    redis: FakeRedis,
    settings: Settings,
) -> None:
    await cache.set("user:1", 42)

    assert redis.ttls[f"{KEY_PREFIX}user:1"] == settings.cache_ttl_seconds


async def test_set_prefers_an_explicit_ttl(cache: CacheService, redis: FakeRedis) -> None:
    await cache.set("user:1", 42, 15)

    assert redis.ttls[f"{KEY_PREFIX}user:1"] == 15


async def test_a_corrupt_entry_is_dropped_and_read_as_a_miss(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    redis.store[f"{KEY_PREFIX}user:1"] = "{not json"

    assert await cache.get("user:1") is None
    assert f"{KEY_PREFIX}user:1" not in redis.store


async def test_a_read_failure_is_reported_as_a_miss(settings: Settings) -> None:
    cache = CacheService(BrokenRedis(), settings)

    assert await cache.get("user:1") is None


async def test_a_write_failure_is_swallowed(settings: Settings) -> None:
    cache = CacheService(BrokenRedis(), settings)

    await cache.set("user:1", {"id": 1})


async def test_a_delete_failure_is_swallowed(settings: Settings) -> None:
    cache = CacheService(BrokenRedis(), settings)

    await cache.delete(["user:1", "user:2"])


async def test_remember_stores_what_the_loader_produced(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    calls = 0

    async def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"total": 7}

    assert await cache.remember("stats", 30, loader) == {"total": 7}
    assert await cache.remember("stats", 30, loader) == {"total": 7}
    # The second call is served from the cache, so the loader ran only once.
    assert calls == 1
    assert redis.ttls[f"{KEY_PREFIX}stats"] == 30


async def test_remember_still_loads_when_the_cache_is_unreachable(settings: Settings) -> None:
    cache = CacheService(BrokenRedis(), settings)

    async def loader() -> str:
        return "from-source"

    assert await cache.remember("stats", 30, loader) == "from-source"


async def test_delete_accepts_a_single_key_and_a_sequence(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    await cache.set("a", 1)
    await cache.set("b", 2)

    await cache.delete("a")
    await cache.delete(["b"])

    assert redis.store == {}


async def test_delete_of_an_empty_sequence_issues_no_command(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    await cache.delete([])

    assert redis.deleted == []


async def test_invalidate_prefix_scans_with_the_client_prefix(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    await cache.set("rbac:user-permissions:1", ["read"])
    await cache.set("rbac:user-permissions:2", ["write"])
    await cache.set("rbac:roles:1", ["admin"])

    await cache.invalidate_prefix("rbac:user-permissions:")

    assert redis.scan_patterns == [f"{KEY_PREFIX}rbac:user-permissions:*"]
    assert list(redis.store) == [f"{KEY_PREFIX}rbac:roles:1"]


async def test_invalidate_prefix_strips_the_prefix_before_deleting(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    await cache.set("rbac:user-permissions:1", ["read"])

    await cache.invalidate_prefix("rbac:user-permissions:")

    # Deletion goes back through the client, which prefixes again — passing the
    # scan reply through unchanged would address `crm:crm:...`.
    assert redis.deleted == [("rbac:user-permissions:1",)]


async def test_invalidate_prefix_survives_a_scan_failure(settings: Settings) -> None:
    cache = CacheService(BrokenRedis(), settings)

    await cache.invalidate_prefix("rbac:")


async def test_noop_cache_stores_nothing_and_always_loads() -> None:
    cache = NoopCacheService()

    async def loader() -> str:
        return "fresh"

    await cache.set("key", "value")
    await cache.delete("key")
    await cache.invalidate_prefix("key")

    assert await cache.get("key") is None
    assert await cache.remember("key", 30, loader) == "fresh"


async def test_an_exotic_value_is_stringified_rather_than_dropped(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    await cache.set("exotic", {"marker": object()})

    assert json.loads(redis.store[f"{KEY_PREFIX}exotic"])["marker"].startswith("<object object")


async def test_a_value_that_cannot_be_encoded_is_not_stored(
    cache: CacheService,
    redis: FakeRedis,
) -> None:
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic

    await cache.set("cyclic", cyclic)

    assert redis.store == {}
