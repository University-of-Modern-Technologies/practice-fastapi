"""The reconciliation rule, exercised without a database anywhere near it.

Every one of the four conditions is tested at its boundary rather than in the
middle, because the middle is not where a rule like this goes wrong: a
tolerance that is exclusive instead of inclusive, or a window that is off by a
day, both behave perfectly on the easy cases and disagree with the sibling
backend on exactly the awkward ones.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.enums import OrderStatus, PaymentMatchStatus
from app.modules.finance.matching import (
    MATCH_AMOUNT_TOLERANCE,
    MATCH_WINDOW_DAYS,
    MATCHABLE_ORDER_STATUSES,
    MatchCandidate,
    MatchSubject,
    amounts_match,
    collapse,
    matches_counterparty,
    outcome_for,
    references_order,
    select_candidates,
    within_window,
)

BOOKED_AT = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
ORDER_CREATED_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

ORDER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ORDER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def make_candidate(**overrides: object) -> MatchCandidate:
    values: dict[str, object] = {
        "order_id": ORDER_ID,
        "order_number": "ORD-2026-0001",
        "status": OrderStatus.CONFIRMED,
        "total": Decimal("1800.00"),
        "created_at": ORDER_CREATED_AT,
        "contact_name": "Alex North",
        "contact_company": "Northwind Workshop",
    }
    return MatchCandidate(**(values | overrides))  # type: ignore[arg-type]


def make_subject(**overrides: object) -> MatchSubject:
    values: dict[str, object] = {
        "amount": Decimal("1800.00"),
        "booked_at": BOOKED_AT,
        "reference": "Payment for ORD-2026-0001",
        "counterparty_name": "Halcyon Supplies",
    }
    return MatchSubject(**(values | overrides))  # type: ignore[arg-type]


# --- the constants the rule turns on --------------------------------------


def test_the_three_knobs_are_named_constants() -> None:
    """They are what the later exercises will move, so they live in one place."""
    assert Decimal("0.01") == MATCH_AMOUNT_TOLERANCE
    assert MATCH_WINDOW_DAYS == 90
    assert MATCHABLE_ORDER_STATUSES == (OrderStatus.CONFIRMED, OrderStatus.PAID)


# --- the amount ------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("1800.00", True),
        # The tolerance is inclusive at both ends: one cent either way is the
        # bank fee, and it is what the rule was written to forgive.
        ("1799.99", True),
        ("1800.01", True),
        ("1799.98", False),
        ("1800.02", False),
    ],
)
def test_the_tolerance_is_exactly_one_cent_either_way(amount: str, expected: bool) -> None:
    assert amounts_match(Decimal(amount), Decimal("1800.00")) is expected


def test_an_amount_is_compared_as_an_exact_decimal() -> None:
    """The comparison a float would get wrong.

    ``0.1 + 0.2`` is not ``0.3`` in binary floating point, so a rule that had
    gone through a float would call this pair different by a hair and refuse a
    payment that is exactly right.
    """
    paid = Decimal("0.1") + Decimal("0.2")

    assert paid == Decimal("0.3")
    assert amounts_match(paid, Decimal("0.30"))


# --- the window ------------------------------------------------------------


def test_a_payment_on_the_day_the_order_was_raised_is_inside_the_window() -> None:
    assert within_window(ORDER_CREATED_AT, ORDER_CREATED_AT)


def test_the_last_day_of_the_window_still_counts() -> None:
    assert within_window(ORDER_CREATED_AT + timedelta(days=MATCH_WINDOW_DAYS), ORDER_CREATED_AT)


def test_a_second_past_the_window_does_not() -> None:
    late = ORDER_CREATED_AT + timedelta(days=MATCH_WINDOW_DAYS, seconds=1)

    assert not within_window(late, ORDER_CREATED_AT)


def test_money_that_arrived_before_the_order_existed_cannot_be_paying_it() -> None:
    assert not within_window(ORDER_CREATED_AT - timedelta(seconds=1), ORDER_CREATED_AT)


# --- the reference ---------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "ORD-2026-0001",
        "payment for ord-2026-0001, thank you",
        "ORD-2026- 0001",
        "  ord-2026-0001  ",
        "ORD-2026-0001 and something else",
    ],
)
def test_a_number_is_found_however_the_payer_spaced_it(reference: str) -> None:
    assert references_order(reference, "ORD-2026-0001")


def test_spaces_in_place_of_the_hyphens_are_not_the_same_number() -> None:
    """The specification forgives case and whitespace, and nothing else.

    A payer who retyped ``ORD 2026 0001`` wrote a different string, and the
    rule says so rather than guessing at what they meant. Widening this is a
    deliberate change with a cost — ``ORD20260001`` is a prefix of a great many
    things — not an oversight to be patched quietly.
    """
    assert not references_order("paid ORD 2026 0001", "ORD-2026-0001")


def test_a_hyphen_is_part_of_the_number_and_is_not_collapsed_away() -> None:
    """Otherwise a longer number would swallow a shorter one.

    ``ORD20260001`` without its hyphens is a prefix of far too many things,
    and a rule that matched on it would attribute payments by coincidence.
    """
    assert not references_order("paid ORD20260001", "ORD-2026-0001")


def test_a_reference_that_names_a_different_order_is_not_a_match() -> None:
    assert not references_order("Payment for ORD-2026-0002", "ORD-2026-0001")


def test_collapse_folds_case_and_whitespace_and_nothing_else() -> None:
    assert collapse("  ORD 2026\t0001 ") == "ord20260001"


# --- the payer -------------------------------------------------------------


@pytest.mark.parametrize("payer", ["Alex North", "alex north", "ALEXNORTH", " Alex  North "])
def test_the_payer_is_recognised_by_the_customer_name(payer: str) -> None:
    assert matches_counterparty(payer, make_candidate())


def test_the_payer_is_recognised_by_the_company_name_too() -> None:
    """Both are the same customer, and a payer types whichever they think of."""
    assert matches_counterparty("Northwind Workshop", make_candidate())


def test_a_partial_name_is_not_a_payer_match() -> None:
    # Containment is right for a reference, which is a sentence, and wrong for
    # a name, which is not: "North" would claim every northern company there is.
    assert not matches_counterparty("North", make_candidate())


def test_an_order_with_no_contact_cannot_be_matched_by_name() -> None:
    orphan = make_candidate(contact_name=None, contact_company=None)

    assert not matches_counterparty("Alex North", orphan)


def test_a_blank_payer_matches_nothing() -> None:
    assert not matches_counterparty("   ", make_candidate())


# --- all four together -----------------------------------------------------


def test_a_quoted_number_with_the_right_amount_in_time_is_a_candidate() -> None:
    assert select_candidates(make_subject(), [make_candidate()]) == [make_candidate()]


def test_the_payer_name_alone_is_enough_when_no_number_was_quoted() -> None:
    subject = make_subject(reference="Monthly settlement", counterparty_name="Alex North")

    assert select_candidates(subject, [make_candidate()]) == [make_candidate()]


def test_neither_a_number_nor_a_name_leaves_nothing_to_go_on() -> None:
    subject = make_subject(reference="Incoming transfer", counterparty_name="Halcyon Supplies")

    assert select_candidates(subject, [make_candidate()]) == []


@pytest.mark.parametrize(
    "status", [OrderStatus.DRAFT, OrderStatus.FULFILLED, OrderStatus.CANCELLED]
)
def test_an_order_in_no_state_to_be_paid_is_never_a_candidate(status: OrderStatus) -> None:
    # A draft has not been agreed and a cancelled order never will be;
    # attributing money to either would claim revenue nobody owes.
    assert select_candidates(make_subject(), [make_candidate(status=status)]) == []


def test_a_right_amount_outside_the_window_is_not_a_candidate() -> None:
    """The line the twelfth row of the bank fixture exists to exercise."""
    stale = make_candidate(created_at=BOOKED_AT - timedelta(days=MATCH_WINDOW_DAYS + 1))

    assert select_candidates(make_subject(), [stale]) == []


def test_the_input_order_of_the_candidates_is_preserved() -> None:
    # Two identical requests have to answer identically, and a list that sorted
    # itself would make the order depend on something the caller did not choose.
    first = make_candidate()
    second = make_candidate(order_id=OTHER_ORDER_ID, order_number="ORD-2026-0009")
    subject = make_subject(reference="Monthly settlement", counterparty_name="Alex North")

    assert select_candidates(subject, [first, second]) == [first, second]


# --- what the count of candidates means ------------------------------------


def test_exactly_one_candidate_is_an_answer() -> None:
    assert outcome_for([make_candidate()]) is PaymentMatchStatus.MATCHED


def test_several_candidates_are_a_question_for_a_person() -> None:
    second = make_candidate(order_id=OTHER_ORDER_ID)

    assert outcome_for([make_candidate(), second]) is PaymentMatchStatus.SUGGESTED


def test_no_candidate_leaves_the_payment_where_it_started() -> None:
    assert outcome_for([]) is PaymentMatchStatus.UNMATCHED
