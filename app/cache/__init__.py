"""Redis-backed caching.

The cache is a latency optimisation and nothing else: every operation here fails
open, so an unreachable Redis degrades response times without ever changing what
the API answers.
"""

from __future__ import annotations

from app.cache.client import (
    CacheRedis,
    PrefixedRedis,
    close_redis_client,
    create_cache_readiness_check,
    create_redis_client,
)
from app.cache.keys import (
    CACHE_KEY_SEPARATOR,
    RBAC_NAMESPACE,
    USER_PERMISSIONS_NAMESPACE,
    cache_key,
    cache_key_prefix,
    user_permissions_key,
    user_permissions_prefix,
)
from app.cache.service import CacheService, NoopCacheService

__all__ = [
    "CACHE_KEY_SEPARATOR",
    "RBAC_NAMESPACE",
    "USER_PERMISSIONS_NAMESPACE",
    "CacheRedis",
    "CacheService",
    "NoopCacheService",
    "PrefixedRedis",
    "cache_key",
    "cache_key_prefix",
    "close_redis_client",
    "create_cache_readiness_check",
    "create_redis_client",
    "user_permissions_key",
    "user_permissions_prefix",
]
