"""Provider-agnostic port for the bank feed.

One verb, one statement, no pagination and no callbacks. Everything above this
interface — the idempotent import, the reconciliation, the audit trail — is
written once and works against the in-repo stub or against whatever a real
bank offers later.

Every way a bank can fail collapses into one reported failure, 502
``BANK_PROVIDER_UNAVAILABLE``. Which way it failed matters to whoever is
debugging the upstream and belongs in the log; to the caller of *our* API the
distinction is meaningless — the statement could not be pulled right now — and
every other endpoint of this module keeps answering while that holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.core.errors import AppError
from app.db.enums import TransactionDirection
from app.modules.finance.types import BANK_PROVIDER_UNAVAILABLE

__all__ = [
    "BankProvider",
    "ProviderStatement",
    "ProviderTransaction",
    "bank_provider_unavailable_error",
]


def bank_provider_unavailable_error() -> AppError:
    """The bank could not be reached, or answered nonsense.

    The message is written for the caller of our API rather than for whoever
    is debugging the upstream: it never carries an endpoint, a credential or
    the bank's own error text. Those stay on our side of the boundary.
    """
    return AppError("The bank provider is temporarily unavailable", 502, BANK_PROVIDER_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class ProviderTransaction:
    """One line of a statement, as the bank reported it.

    Deliberately separate from the stored model and from the wire schema: a
    bank is free to change its payload, and only the mapping layer has to
    follow. It carries nothing about reconciliation — the bank knows what
    arrived, not what it was for.
    """

    external_id: str
    booked_at: datetime
    amount: Decimal
    currency: str
    direction: TransactionDirection
    counterparty_name: str
    reference: str
    counterparty_account: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderStatement:
    """One period of account activity, with the lines that make it up."""

    external_id: str
    account_label: str
    period_start: date
    period_end: date
    currency: str
    opening_balance: Decimal
    closing_balance: Decimal
    transactions: tuple[ProviderTransaction, ...]


class BankProvider(Protocol):
    """Anything that can hand over a statement."""

    @property
    def name(self) -> str:
        """Identifies the implementation in health output and logs."""

    async def fetch_statement(self) -> ProviderStatement: ...
