"""In-repo stand-in for the bank feed.

The default configuration names no bank, and without this the module would be
dead on a fresh checkout: nothing to import, nothing to reconcile, nothing to
disagree about. The stub keeps the system runnable end to end with no account,
no key and no network.

It is not, however, merely a placeholder. What an import files is visible
through the API a moment later, which makes this table shared data rather than
an implementation detail — the same twelve lines have to come out of both
backends. So the fixture is fixed, it is generated from constants rather than
from the clock, and it is arranged so that every branch of the reconciliation
rule is reachable from it:

* ``0001`` to ``0003`` quote an order number and pay it to the cent;
* ``0004`` is a cent short: inside the tolerance, not equal to it;
* ``0005`` quotes no number at all, and the payer is named as the person;
* ``0006`` has an amount and a reference that fit nothing;
* ``0007`` and ``0008`` share an amount and a payer — the company name this
  time — and name no order, which is the whole of what makes a suggestion a
  suggestion;
* ``0009`` to ``0011`` are money going out, which is never reconciled;
* ``0012`` pays an order placed almost half a year earlier.

The last line earns its place: without it the ninety-day window is a rule that
has been written down but never once exercised.

Every date here is absolute, and so is every date in the orders these lines are
meant to meet. Nothing is derived from the clock, so the same checkout run six
months from now imports the same statement and reconciles to the same five
matches, two suggestions, two unmatched lines and three ignored ones.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.db.enums import TransactionDirection
from app.modules.finance.provider import ProviderStatement, ProviderTransaction

__all__ = [
    "STUB_BANK_PROVIDER_NAME",
    "STUB_OPENING_BALANCE",
    "STUB_STATEMENT_EXTERNAL_ID",
    "STUB_TRANSACTION_COUNT",
    "StubBankProvider",
    "create_stub_bank_provider",
    "stub_statement",
]

STUB_BANK_PROVIDER_NAME = "stub"

STUB_STATEMENT_EXTERNAL_ID = "stub-stmt-2026-01"
STUB_ACCOUNT_LABEL = "Operating account"
STUB_PERIOD_START = date(2026, 1, 1)
STUB_PERIOD_END = date(2026, 1, 31)
STUB_CURRENCY = "USD"
STUB_OPENING_BALANCE = Decimal("10000.00")

#: First line of the statement. Fixed, so a second import of the same feed
#: files nothing rather than merely being likely to.
_ANCHOR = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)

#: Spacing between consecutive lines, counting forwards.
_STEP = timedelta(days=2)

_CREDIT = TransactionDirection.CREDIT
_DEBIT = TransactionDirection.DEBIT

#: The payers, named once so a line of the table stays readable and so the two
#: lines that have to share a payer cannot drift apart by a typo. Both ways of
#: writing a customer down appear: a company pays lines 1 to 4 and 7 to 8, a
#: person pays line 5, and the rule has to recognise either.
_NORTHWIND = "Northwind Workshop"
_CEDAR_LABS = "Cedar Labs"
_BLUE_PEAK = "Blue Peak Studio"
_JORDAN = "Jordan Blue"

#: The statement as data: direction, amount, payer, account, reference. The
#: order of the rows is the order of the identifiers ``stub-txn-2026-01-0001``
#: and of the booking dates, so the table reads as the account does.
_LINES: tuple[tuple[TransactionDirection, str, str, str | None, str], ...] = (
    (_CREDIT, "1800.00", _NORTHWIND, "ACCT-1001", "Payment for order ORD-2026-0001"),
    (_CREDIT, "2400.00", _CEDAR_LABS, "ACCT-1002", "ORD-2026-0004 settled"),
    (_CREDIT, "450.00", _BLUE_PEAK, "ACCT-1003", "Remittance for ORD-2026-0005"),
    # A cent short of the order it names: the tolerance exists for this line.
    (_CREDIT, "1249.99", _NORTHWIND, "ACCT-1004", "Order ORD-2026-0006, net of transfer fee"),
    # Nothing to key on but the payer's own name, and it is the person's.
    (_CREDIT, "777.00", _JORDAN, None, "Wire transfer"),
    # Fits nothing, and stays that way.
    (_CREDIT, "66.00", "Unknown Payer", None, "General deposit"),
    # Twice the same payer for the same amount, with nothing to tell them apart.
    (_CREDIT, "990.00", _CEDAR_LABS, "ACCT-1007", "Bank transfer"),
    (_CREDIT, "990.00", _CEDAR_LABS, "ACCT-1008", "Bank transfer"),
    (_DEBIT, "3200.00", "City Property Management", "ACCT-1009", "Office rent, January"),
    (_DEBIT, "5400.00", "Payroll Services Ltd", "ACCT-1010", "Payroll, January"),
    (_DEBIT, "640.00", "Cloud Hosting Inc", "ACCT-1011", "Hosting and services"),
    # Pays an order placed almost half a year earlier: outside the window.
    (_CREDIT, "1500.00", _NORTHWIND, "ACCT-1012", "Payment for order ORD-2025-0099"),
)

#: How many lines one import brings in. Derived rather than repeated, so the
#: table above stays the only place the fixture is stated.
STUB_TRANSACTION_COUNT = len(_LINES)


def _transaction(index: int) -> ProviderTransaction:
    """One line of the statement.

    The period is part of the identifier rather than decoration. Import is
    idempotent by external id, so a fixture whose contents change while its
    ids stay the same is invisible to a database that already holds the old
    rows: the import reports twelve skipped and the ledger keeps yesterday's
    data for ever. A revised statement gets revised identifiers.
    """
    direction, amount, counterparty, account, reference = _LINES[index]
    return ProviderTransaction(
        external_id=f"stub-txn-2026-01-{index + 1:04d}",
        booked_at=_ANCHOR + _STEP * index,
        amount=Decimal(amount),
        currency=STUB_CURRENCY,
        direction=direction,
        counterparty_name=counterparty,
        counterparty_account=account,
        reference=reference,
    )


def _closing_balance(transactions: tuple[ProviderTransaction, ...]) -> Decimal:
    """What the account is left holding: the opening balance plus the flow.

    Computed from the lines rather than written down beside them, because a
    balance quoted as a constant is one that goes quietly wrong the first time
    a line is edited.
    """
    balance = STUB_OPENING_BALANCE
    for item in transactions:
        if item.direction is TransactionDirection.CREDIT:
            balance += item.amount
        else:
            balance -= item.amount
    return balance


def stub_statement() -> ProviderStatement:
    """The one statement the stub knows, built from the table above."""
    transactions = tuple(_transaction(index) for index in range(STUB_TRANSACTION_COUNT))
    return ProviderStatement(
        external_id=STUB_STATEMENT_EXTERNAL_ID,
        account_label=STUB_ACCOUNT_LABEL,
        period_start=STUB_PERIOD_START,
        period_end=STUB_PERIOD_END,
        currency=STUB_CURRENCY,
        opening_balance=STUB_OPENING_BALANCE,
        closing_balance=_closing_balance(transactions),
        transactions=transactions,
    )


class StubBankProvider:
    """Answers the bank protocol from memory, without a network call."""

    name = STUB_BANK_PROVIDER_NAME

    def __init__(self) -> None:
        self._statement = stub_statement()

    async def fetch_statement(self) -> ProviderStatement:
        return self._statement


def create_stub_bank_provider() -> StubBankProvider:
    """Builds the offline provider."""
    return StubBankProvider()
