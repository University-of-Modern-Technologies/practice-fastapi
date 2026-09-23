"""Vocabulary of the finance module.

Two things live here rather than next to the code that uses them.

The machine codes, for the reason every module in this codebase keeps them in
one place: a client branches on the string, so a rename that reached only one
of the two call sites would be invisible until somebody's error handling
stopped firing.

And the shape a monetary amount has on the wire. The pattern is stated here
because this module accepts amounts as filters, and an amount that arrived as
a number would already have been through a float by the time any code of ours
saw it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.enums import PermissionScope

__all__ = [
    "BANK_PROVIDER_UNAVAILABLE",
    "MAX_ACCOUNT_LABEL_LENGTH",
    "MAX_COUNTERPARTY_ACCOUNT_LENGTH",
    "MAX_COUNTERPARTY_NAME_LENGTH",
    "MAX_EXTERNAL_ID_LENGTH",
    "MAX_REFERENCE_LENGTH",
    "MAX_SEARCH_LENGTH",
    "MONEY_STRING_PATTERN",
    "STATEMENT_DUPLICATE_EXTERNAL_ID",
    "STATEMENT_ENTITY_TYPE",
    "STATEMENT_IMPORTED",
    "STATEMENT_NOT_FOUND",
    "TRANSACTION_ALREADY_MATCHED",
    "TRANSACTION_AMOUNT_MISMATCH",
    "TRANSACTION_CONCURRENT_MODIFICATION",
    "TRANSACTION_ENTITY_TYPE",
    "TRANSACTION_MATCHED",
    "TRANSACTION_NOT_FOUND",
    "TRANSACTION_NOT_MATCHED",
    "TRANSACTION_ORDER_NOT_FOUND",
    "TRANSACTION_UNMATCHED",
    "FinanceAccess",
    "StatementSortField",
    "TransactionSortField",
]

#: Machine codes, each spelled exactly as its value.
TRANSACTION_NOT_FOUND = "TRANSACTION_NOT_FOUND"
STATEMENT_NOT_FOUND = "STATEMENT_NOT_FOUND"
TRANSACTION_ALREADY_MATCHED = "TRANSACTION_ALREADY_MATCHED"
TRANSACTION_NOT_MATCHED = "TRANSACTION_NOT_MATCHED"
TRANSACTION_ORDER_NOT_FOUND = "TRANSACTION_ORDER_NOT_FOUND"
TRANSACTION_AMOUNT_MISMATCH = "TRANSACTION_AMOUNT_MISMATCH"
#: Optimistic locking is reported per resource, so a client that races on a
#: reconciliation knows which of the records in front of it to re-read.
TRANSACTION_CONCURRENT_MODIFICATION = "TRANSACTION_CONCURRENT_MODIFICATION"
STATEMENT_DUPLICATE_EXTERNAL_ID = "STATEMENT_DUPLICATE_EXTERNAL_ID"
BANK_PROVIDER_UNAVAILABLE = "BANK_PROVIDER_UNAVAILABLE"

#: Audit actions and domain event types — deliberately the same strings, so one
#: change is described by one name wherever it is read back.
TRANSACTION_MATCHED = "transaction.matched"
TRANSACTION_UNMATCHED = "transaction.unmatched"
STATEMENT_IMPORTED = "statement.imported"

#: Entity types carried by the audit trail and the event stream.
TRANSACTION_ENTITY_TYPE = "transaction"
STATEMENT_ENTITY_TYPE = "statement"

MAX_EXTERNAL_ID_LENGTH = 64
MAX_ACCOUNT_LABEL_LENGTH = 64
MAX_COUNTERPARTY_NAME_LENGTH = 200
MAX_COUNTERPARTY_ACCOUNT_LENGTH = 64
MAX_REFERENCE_LENGTH = 300
MAX_SEARCH_LENGTH = 160

#: Shape a monetary amount has on the wire: up to twelve digits in front of the
#: point and at most two behind it, which is what ``Numeric(14, 2)`` holds.
#: Stated as a string pattern because a JSON number would have gone through a
#: float in the client before this process ever saw it.
MONEY_STRING_PATTERN = r"^\d{1,12}(?:\.\d{1,2})?$"

#: Columns a client may sort the ledger by, spelled as the client spells them.
#: ``bookedAt`` is the default rather than ``createdAt``: a ledger is read as
#: the account's own timeline, not as the order the import happened to file it.
TransactionSortField = Literal[
    "bookedAt",
    "amount",
    "createdAt",
]

#: Statements are read newest period first, so the period is the default sort.
StatementSortField = Literal[
    "periodStart",
    "importedAt",
    "createdAt",
]


@dataclass(frozen=True, slots=True)
class FinanceAccess:
    """Who is acting on the ledger, and how broad their grant is.

    The scope travels with the actor rather than being resolved inside the
    service: only the caller knows which permission was checked.

    Unlike every other module in this codebase, nothing here narrows to it.
    A bank statement belongs to the company rather than to a colleague — there
    is no ``owner_id`` on either table to compare against — so a grant of
    ``OWN`` would have no column to mean anything by. It is carried, recorded
    and deliberately not acted on, rather than silently reinterpreted as some
    neighbouring relation such as "whoever reconciled it": a caller who could
    see only the payments they had already matched could never find the one
    they had not.

    The canonical role layout grants nobody ``OWN`` on this resource, so this
    is a statement about a case that does not arise rather than a behaviour
    anybody exercises.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None

    @property
    def owned_only(self) -> bool:
        """Whether the grant is the narrow one; see the note above on effect."""
        return self.scope is PermissionScope.OWN
