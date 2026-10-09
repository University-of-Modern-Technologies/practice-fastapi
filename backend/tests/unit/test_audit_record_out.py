"""An audit entry always carries ``changes`` and ``metadata``.

The description marks both as required and as an object or ``null``; that holds
only while an entry with nothing recorded still sends the keys.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.audit.schemas import AuditRecordOut

RECORD: dict[str, Any] = {
    "id": uuid.UUID("60000000-0000-4000-8000-000000000001"),
    "actor_id": None,
    "action": "contact.created",
    "entity_type": "contact",
    "entity_id": None,
    "ip_address": None,
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
}


def test_an_entry_with_nothing_recorded_still_sends_both_keys() -> None:
    body = AuditRecordOut(**RECORD, changes=None, metadata=None).model_dump(
        mode="json", by_alias=True
    )

    assert body["changes"] is None
    assert body["metadata"] is None


def test_a_recorded_change_is_sent_as_the_object_it_was_stored_as() -> None:
    changes = {"before": {"name": "Ada"}, "after": {"name": "Ada L."}}

    body = AuditRecordOut(**RECORD, changes=changes, metadata={"source": "import"}).model_dump(
        mode="json", by_alias=True
    )

    assert body["changes"] == changes
    assert body["metadata"] == {"source": "import"}


def test_the_published_shape_requires_both_keys() -> None:
    schema = AuditRecordOut.model_json_schema(by_alias=True, mode="serialization")

    assert {"changes", "metadata"} <= set(schema["required"])


def test_an_entry_cannot_be_built_without_saying_what_changed() -> None:
    with pytest.raises(ValidationError):
        AuditRecordOut(**RECORD)
