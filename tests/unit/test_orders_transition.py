"""The order lifecycle: which moves exist, and which never will."""

from __future__ import annotations

import pytest

from app.core.errors import ConflictError
from app.db.enums import OrderStatus
from app.modules.orders.transition import (
    assert_order_editable,
    assert_order_has_items,
    assert_order_status_transition,
    can_transition_order_status,
    is_order_editable,
)

#: Spelled out again rather than imported, so a change to the table has to be
#: made deliberately in two places.
EXPECTED: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.FULFILLED, OrderStatus.CANCELLED},
    OrderStatus.FULFILLED: set(),
    OrderStatus.CANCELLED: set(),
}


class TestStatusMatrix:
    @pytest.mark.parametrize("from_status", list(OrderStatus))
    def test_allows_exactly_the_documented_moves(self, from_status: OrderStatus) -> None:
        for to_status in OrderStatus:
            assert can_transition_order_status(from_status, to_status) is (
                to_status in EXPECTED[from_status]
            )

    def test_never_returns_to_a_previous_stage_or_repeats_itself(self) -> None:
        assert not can_transition_order_status(OrderStatus.CONFIRMED, OrderStatus.DRAFT)
        assert not can_transition_order_status(OrderStatus.PAID, OrderStatus.CONFIRMED)
        assert not can_transition_order_status(OrderStatus.FULFILLED, OrderStatus.PAID)
        assert not can_transition_order_status(OrderStatus.DRAFT, OrderStatus.DRAFT)

    def test_never_cancels_a_fulfilled_order_and_never_revives_a_cancelled_one(self) -> None:
        assert not can_transition_order_status(OrderStatus.FULFILLED, OrderStatus.CANCELLED)
        assert not can_transition_order_status(OrderStatus.CANCELLED, OrderStatus.CONFIRMED)

    def test_skips_no_stage_on_the_happy_path(self) -> None:
        assert not can_transition_order_status(OrderStatus.DRAFT, OrderStatus.PAID)
        assert not can_transition_order_status(OrderStatus.CONFIRMED, OrderStatus.FULFILLED)

    def test_reports_a_forbidden_move_as_a_conflict_carrying_the_allowed_ones(self) -> None:
        with pytest.raises(ConflictError) as error:
            assert_order_status_transition(OrderStatus.FULFILLED, OrderStatus.CANCELLED)

        assert error.value.status_code == 409
        assert error.value.code == "INVALID_ORDER_STATUS_TRANSITION"
        assert error.value.details == {"from": "FULFILLED", "to": "CANCELLED", "allowed": []}

    def test_lets_an_admitted_move_through(self) -> None:
        assert_order_status_transition(OrderStatus.DRAFT, OrderStatus.CONFIRMED)


class TestEditability:
    def test_treats_only_a_draft_as_editable(self) -> None:
        assert is_order_editable(OrderStatus.DRAFT)
        assert_order_editable(OrderStatus.DRAFT)

    @pytest.mark.parametrize(
        "status",
        [status for status in OrderStatus if status is not OrderStatus.DRAFT],
    )
    def test_refuses_to_reshape_an_order_that_was_placed(self, status: OrderStatus) -> None:
        assert not is_order_editable(status)

        with pytest.raises(ConflictError) as error:
            assert_order_editable(status)
        assert error.value.status_code == 409
        assert error.value.code == "ORDER_NOT_EDITABLE"

    def test_keeps_an_empty_order_in_the_draft_stage(self) -> None:
        with pytest.raises(ConflictError) as error:
            assert_order_has_items(OrderStatus.DRAFT, 0)
        assert error.value.code == "ORDER_HAS_NO_ITEMS"

        assert_order_has_items(OrderStatus.DRAFT, 1)
        # Once the order has left the draft stage the guard no longer applies.
        assert_order_has_items(OrderStatus.CONFIRMED, 0)
