"""Cache key construction."""

from __future__ import annotations

from app.cache.keys import (
    CACHE_KEY_SEPARATOR,
    cache_key,
    cache_key_prefix,
    user_permissions_key,
    user_permissions_prefix,
)


def test_cache_key_joins_segments_with_the_separator() -> None:
    assert cache_key("rbac", "user-permissions", "42") == "rbac:user-permissions:42"


def test_cache_key_of_a_single_segment_is_the_segment() -> None:
    assert cache_key("rbac") == "rbac"


def test_prefix_ends_with_the_separator() -> None:
    prefix = cache_key_prefix("rbac", "user-permissions")

    assert prefix.endswith(CACHE_KEY_SEPARATOR)
    assert prefix == "rbac:user-permissions:"


def test_prefix_does_not_match_a_sibling_namespace() -> None:
    # The trailing separator is what keeps `rbac:user` from also dropping
    # `rbac:users-something`.
    assert not "rbac:user-permissions-archive".startswith(cache_key_prefix("rbac", "user"))


def test_user_permission_keys_live_under_the_user_permission_prefix() -> None:
    assert user_permissions_key("42").startswith(user_permissions_prefix())
    assert user_permissions_key("42") == "rbac:user-permissions:42"
