"""The reconciliation rule, written down once.

This file is the normative statement of when a bank transaction is taken to
pay for an order. Everything else in the module — the SQL that narrows the
search, the endpoints that report the outcome — is arranged around it, and the
SQL may only ever narrow by the same conditions, never by different ones.

The four conditions are deliberately all evaluated here, in Python, even
though a query has already applied most of them. A rule split between a
``WHERE`` clause and a function is a rule nobody can read in one place, and the
cost of checking a handful of already-narrowed rows a second time is nothing
next to that.

The three numbers the rule turns on — the tolerance, the window and which
order statuses may be paid at all — are module constants rather than literals
buried in a predicate. They are the part of this file most likely to be
changed, and a change to any of them has to be visible in one place.

Nothing here touches a float. Amounts are compared as exact decimals, so the
tolerance means one cent rather than something within a rounding error of one
cent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.db.enums import OrderStatus, PaymentMatchStatus

__all__ = [
    "MATCHABLE_ORDER_STATUSES",
    "MATCH_AMOUNT_TOLERANCE",
    "MATCH_WINDOW_DAYS",
    "MatchCandidate",
    "MatchSubject",
    "amounts_match",
    "collapse",
    "matches_counterparty",
    "outcome_for",
    "references_order",
    "select_candidates",
    "within_window",
]

#: How far an amount may differ from an order total and still be taken as
#: paying it. One cent: the difference a bank fee or a rounding step on the
#: payer's side produces, and no more.
MATCH_AMOUNT_TOLERANCE = Decimal("0.01")

#: How long after an order was raised a payment may still be attributed to it.
#: Ninety days is a quarter — long enough for an invoice on payment terms,
#: short enough that a coincidence a year later is not read as a settlement.
MATCH_WINDOW_DAYS = 90

#: The only states in which an order is waiting for money. A draft has not been
#: agreed yet and a cancelled order never will be, and attributing a payment to
#: either would make a reconciliation report claim revenue that nobody owes.
MATCHABLE_ORDER_STATUSES: tuple[OrderStatus, ...] = (OrderStatus.CONFIRMED, OrderStatus.PAID)

#: The window, as the interval the arithmetic actually uses.
MATCH_WINDOW = timedelta(days=MATCH_WINDOW_DAYS)


@dataclass(frozen=True, slots=True)
class MatchSubject:
    """The transaction side of the question: what arrived, and when.

    A flat value rather than the model, so the rule can be exercised — and
    argued about — without a database anywhere near it.
    """

    amount: Decimal
    booked_at: datetime
    reference: str
    counterparty_name: str


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """An order the payment might belong to, with everything the rule reads.

    ``contact_name`` and ``contact_company`` are the two ways a customer can be
    written down in this system, and a payer types whichever they think of.
    Both are carried because both are compared.
    """

    order_id: uuid.UUID
    order_number: str
    status: OrderStatus
    total: Decimal
    created_at: datetime
    contact_name: str | None = None
    contact_company: str | None = None


def collapse(value: str) -> str:
    """Folds text to the form the rule compares by: lower case, no whitespace.

    "Без урахування регістру й пробілів" in the specification is exactly this:
    ``ORD 2026 0001``, ``ord-2026-0001`` and ``Ord2026 0001`` are the same
    reference as far as reconciliation is concerned, because a payer retyping
    a number off an invoice will space it however their keyboard felt at the
    time. Hyphens are *not* removed — they are part of the number itself, and
    dropping them would make ``ORD-2026-0001`` match ``ORD20260001999``.
    """
    return "".join(value.split()).casefold()


def amounts_match(amount: Decimal, total: Decimal) -> bool:
    """Whether a paid amount is the order total, to within the tolerance."""
    return abs(amount - total) <= MATCH_AMOUNT_TOLERANCE


def within_window(booked_at: datetime, order_created_at: datetime) -> bool:
    """Whether the payment fell inside the order's collection window.

    Closed at both ends. Money that arrived before the order existed cannot be
    paying it, and money that arrived a quarter later is a different
    transaction that happens to be for a similar sum.
    """
    return order_created_at <= booked_at <= order_created_at + MATCH_WINDOW


def references_order(reference: str, order_number: str) -> bool:
    """Whether the payer wrote the order number into the payment reference.

    Containment rather than equality: a reference is free text, and the number
    arrives wrapped in whatever sentence the payer typed around it.
    """
    collapsed_number = collapse(order_number)
    return bool(collapsed_number) and collapsed_number in collapse(reference)


def matches_counterparty(counterparty_name: str, candidate: MatchCandidate) -> bool:
    """Whether the payer is, by name, the customer the order belongs to.

    The weaker of the two identifying conditions, and the one that makes the
    module interesting: a person and a company are two different names for the
    same customer, people pay from an account in either name, and neither is
    unique. That is why a name match alone never settles anything — it
    produces a candidate, and the count of candidates decides the outcome.
    """
    payer = collapse(counterparty_name)
    if not payer:
        return False
    known = [name for name in (candidate.contact_name, candidate.contact_company) if name]
    return any(payer == collapse(name) for name in known)


def _is_candidate(subject: MatchSubject, candidate: MatchCandidate) -> bool:
    """All four conditions, in the order the specification states them."""
    return (
        candidate.status in MATCHABLE_ORDER_STATUSES
        and (
            references_order(subject.reference, candidate.order_number)
            or matches_counterparty(subject.counterparty_name, candidate)
        )
        and amounts_match(subject.amount, candidate.total)
        and within_window(subject.booked_at, candidate.created_at)
    )


def select_candidates(
    subject: MatchSubject, candidates: list[MatchCandidate]
) -> list[MatchCandidate]:
    """Every order the payment could be settling, in the order given.

    The input order is preserved rather than re-sorted: the caller has already
    decided what a stable order is, and a list that reshuffled itself would
    make two identical requests answer differently.
    """
    return [candidate for candidate in candidates if _is_candidate(subject, candidate)]


def outcome_for(candidates: list[MatchCandidate]) -> PaymentMatchStatus:
    """What the count of candidates means.

    Exactly one is an answer. More than one is a question for a human, which
    is what ``SUGGESTED`` says. None leaves the transaction where it started —
    and the volume of those is the honest measure of how well the rule works,
    which is why they are not hidden behind a status of their own.
    """
    if len(candidates) == 1:
        return PaymentMatchStatus.MATCHED
    if len(candidates) > 1:
        return PaymentMatchStatus.SUGGESTED
    return PaymentMatchStatus.UNMATCHED
