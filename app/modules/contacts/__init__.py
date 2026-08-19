"""The contact directory: people and companies the organization deals with.

Mount with ``create_contacts_router()`` under ``/api/v1/contacts``.
"""

from __future__ import annotations

from app.modules.contacts.router import create_contacts_router, get_contacts_service
from app.modules.contacts.schemas import (
    ContactListParams,
    ContactOut,
    CreateContactRequest,
    UpdateContactRequest,
)
from app.modules.contacts.service import ContactsService, to_contact_out
from app.modules.contacts.types import (
    CONTACT_CHANNEL_REQUIRED,
    CONTACT_DUPLICATE,
    CONTACT_NOT_FOUND,
    ContactAccess,
    ContactSortField,
)

__all__ = [
    "CONTACT_CHANNEL_REQUIRED",
    "CONTACT_DUPLICATE",
    "CONTACT_NOT_FOUND",
    "ContactAccess",
    "ContactListParams",
    "ContactOut",
    "ContactSortField",
    "ContactsService",
    "CreateContactRequest",
    "UpdateContactRequest",
    "create_contacts_router",
    "get_contacts_service",
    "to_contact_out",
]
