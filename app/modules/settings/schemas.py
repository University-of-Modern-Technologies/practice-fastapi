"""Wire contract of the settings endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.core.responses import CamelModel
from app.modules.settings.types import SettingSource

MAX_DESCRIPTION_LENGTH = 255
MAX_KEY_LENGTH = 100

#: The key is only shape-checked at the boundary; whether it is a declared key,
#: and whether the value fits it, is decided by the registry.
KEY_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$"


class SettingOut(CamelModel):
    """One setting as the API publishes it.

    ``updated_at`` is already a string rather than a datetime: the DTO is stored
    in the cache as JSON, and a shape that survives that round trip unchanged is
    one shape fewer to keep in step.
    """

    key: str
    value: Any
    description: str
    updated_by_id: uuid.UUID | None
    updated_at: str | None
    source: SettingSource


class UpsertSettingRequest(CamelModel):
    """Body of ``PUT /settings/{key}``."""

    #: Required, and deliberately untyped here: the type is whatever the
    #: registry declares for the key in the path.
    value: Any
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
