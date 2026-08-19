"""Organization settings: a declared, typed, cached key-value store.

Mount with ``create_settings_router()`` under ``/api/v1/settings``. Other
modules read a value through ``SettingsService.get``.
"""

from __future__ import annotations

from app.modules.settings.cache_keys import (
    setting_value_key,
    settings_list_key,
    settings_prefix,
)
from app.modules.settings.registry import (
    SETTING_KEYS,
    SETTING_REGISTRY,
    SettingDefinition,
    ensure_setting_key,
    is_setting_key,
    parse_setting_value,
    read_stored_value,
    setting_default,
    setting_definition,
)
from app.modules.settings.router import create_settings_router, get_settings_service
from app.modules.settings.schemas import SettingOut, UpsertSettingRequest
from app.modules.settings.service import SettingsService, to_setting_out
from app.modules.settings.types import SettingsAccess

__all__ = [
    "SETTING_KEYS",
    "SETTING_REGISTRY",
    "SettingDefinition",
    "SettingOut",
    "SettingsAccess",
    "SettingsService",
    "UpsertSettingRequest",
    "create_settings_router",
    "ensure_setting_key",
    "get_settings_service",
    "is_setting_key",
    "parse_setting_value",
    "read_stored_value",
    "setting_default",
    "setting_definition",
    "setting_value_key",
    "settings_list_key",
    "settings_prefix",
    "to_setting_out",
]
