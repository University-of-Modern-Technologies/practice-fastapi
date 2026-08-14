"""Cache key construction.

Keys are built from colon-separated segments so that every feature owns a
namespace and whole namespaces can be dropped with a single prefix scan.
"""

from __future__ import annotations

CACHE_KEY_SEPARATOR = ":"

RBAC_NAMESPACE = "rbac"
USER_PERMISSIONS_NAMESPACE = "user-permissions"


def cache_key(*segments: str) -> str:
    return CACHE_KEY_SEPARATOR.join(segments)


def cache_key_prefix(*segments: str) -> str:
    """Namespace prefix for a scan.

    A prefix always ends with the separator so that ``rbac:user`` never matches
    ``rbac:users-something``.
    """
    return f"{cache_key(*segments)}{CACHE_KEY_SEPARATOR}"


def user_permissions_key(user_id: str) -> str:
    return cache_key(RBAC_NAMESPACE, USER_PERMISSIONS_NAMESPACE, user_id)


def user_permissions_prefix() -> str:
    return cache_key_prefix(RBAC_NAMESPACE, USER_PERMISSIONS_NAMESPACE)
