"""Cache keys of the settings namespace.

Module-local builders: the shared ``app.cache.keys`` only owns namespaces that
more than one module needs, so the settings namespace lives here.
"""

from __future__ import annotations

from app.cache.keys import cache_key, cache_key_prefix

__all__ = [
    "SETTINGS_NAMESPACE",
    "setting_value_key",
    "settings_list_key",
    "settings_prefix",
]

SETTINGS_NAMESPACE = "settings"


def setting_value_key(key: str) -> str:
    """Entry holding one setting."""
    return cache_key(SETTINGS_NAMESPACE, "value", key)


def settings_list_key() -> str:
    """Entry holding the whole listing."""
    return cache_key(SETTINGS_NAMESPACE, "list")


def settings_prefix() -> str:
    """Prefix covering every settings entry, for a wholesale drop."""
    return cache_key_prefix(SETTINGS_NAMESPACE)
