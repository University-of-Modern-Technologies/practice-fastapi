"""Proves that everything the module knows about an order status now lives
in exactly one place: :mod:`app.modules.orders.state`.
"""

from __future__ import annotations

import pytest

from app.db.enums import OrderStatus
from app.modules.orders.state import order_state
from app.modules.orders.stock import stock_effect_for_transition
from app.modules.orders.transition import ALLOWED_ORDER_STATUS_TRANSITIONS, is_order_editable

#: The historical table, kept here only as a fixed point to compare the
#: single-source-of-truth states against. If a status is ever added without
#: updating ``state.py``, one of these comparisons catches it.
HISTORICAL_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.FULFILLED, OrderStatus.CANCELLED},
    OrderStatus.FULFILLED: set(),
    OrderStatus.CANCELLED: set(),
}


def _historical_stock_effect(from_status: OrderStatus, to_status: OrderStatus) -> str | None:
    if from_status is OrderStatus.DRAFT and to_status is OrderStatus.CONFIRMED:
        return "reserve"
    if to_status is OrderStatus.CANCELLED and from_status in (
        OrderStatus.CONFIRMED,
        OrderStatus.PAID,
    ):
        return "release"
    if from_status is OrderStatus.PAID and to_status is OrderStatus.FULFILLED:
        return "issue"
    return None


class TestOrderStateRegistry:
    @pytest.mark.parametrize("status", list(OrderStatus))
    def test_has_exactly_one_state_per_status(self, status: OrderStatus) -> None:
        assert order_state(status).status is status

    @pytest.mark.parametrize("status", list(OrderStatus))
    def test_carries_the_same_transitions_as_the_historical_table(
        self, status: OrderStatus
    ) -> None:
        assert set(order_state(status).allowed_transitions) == HISTORICAL_TRANSITIONS[status]
        assert set(ALLOWED_ORDER_STATUS_TRANSITIONS[status]) == HISTORICAL_TRANSITIONS[status]

    def test_carries_the_same_stock_effect_as_the_historical_function_for_every_pair(
        self,
    ) -> None:
        for from_status in OrderStatus:
            for to_status in OrderStatus:
                expected = _historical_stock_effect(from_status, to_status)
                assert order_state(from_status).stock_effect(to_status) == expected
                assert stock_effect_for_transition(from_status, to_status) == expected

    @pytest.mark.parametrize("status", list(OrderStatus))
    def test_marks_only_draft_editable_and_only_draft_as_requiring_items(
        self, status: OrderStatus
    ) -> None:
        expected = status is OrderStatus.DRAFT
        assert order_state(status).is_editable is expected
        assert is_order_editable(status) is expected
        assert order_state(status).requires_items is expected
