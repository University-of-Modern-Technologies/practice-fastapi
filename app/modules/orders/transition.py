"""The order lifecycle, as a set of pure predicates.

``CANCELLED`` is reachable from every stage that has not been fulfilled yet; a
fulfilled order is final, because the goods have already left the warehouse. A
status therefore never moves backwards and never repeats itself, which is what
lets the stock effects in :mod:`app.modules.orders.stock` be derived from the
pair of statuses alone.

The rules themselves live one object per status in
:mod:`app.modules.orders.state`; the functions here are thin wrappers so that
existing callers and tests keep addressing this module by name.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.errors import ConflictError
from app.db.enums import OrderStatus
from app.modules.orders.state import order_state
from app.modules.orders.types import (
    INVALID_ORDER_STATUS_TRANSITION,
    ORDER_HAS_NO_ITEMS,
    ORDER_NOT_EDITABLE,
)

__all__ = [
    "ALLOWED_ORDER_STATUS_TRANSITIONS",
    "assert_order_editable",
    "assert_order_has_items",
    "assert_order_status_transition",
    "can_transition_order_status",
    "is_order_editable",
]

#: Derived from the states rather than written out again, so this table and
#: the one baked into each state can never drift apart.
ALLOWED_ORDER_STATUS_TRANSITIONS: Mapping[OrderStatus, tuple[OrderStatus, ...]] = {
    status: order_state(status).allowed_transitions for status in OrderStatus
}


def can_transition_order_status(from_status: OrderStatus, to_status: OrderStatus) -> bool:
    """Whether the lifecycle admits this move."""
    return to_status in order_state(from_status).allowed_transitions


def assert_order_status_transition(from_status: OrderStatus, to_status: OrderStatus) -> None:
    """Rejects a move the lifecycle does not admit, naming the ones it does."""
    if not can_transition_order_status(from_status, to_status):
        raise ConflictError(
            f"Order status cannot transition from {from_status} to {to_status}",
            INVALID_ORDER_STATUS_TRANSITION,
            {
                "from": from_status.value,
                "to": to_status.value,
                "allowed": [
                    status.value for status in order_state(from_status).allowed_transitions
                ],
            },
        )


def is_order_editable(status: OrderStatus) -> bool:
    """Lines and monetary fields may only be reshaped while the order is a draft."""
    return order_state(status).is_editable


def assert_order_editable(status: OrderStatus) -> None:
    """Rejects a change of shape to an order that has already been placed."""
    if not is_order_editable(status):
        raise ConflictError(
            "Order items can only be changed while the order is a draft "
            f"(current status: {status})",
            ORDER_NOT_EDITABLE,
            {"status": status.value},
        )


def assert_order_has_items(status: OrderStatus, item_count: int) -> None:
    """An empty order carries no value, so it may never leave the draft stage."""
    if order_state(status).requires_items and item_count == 0:
        raise ConflictError(
            "An order without items cannot leave the draft stage",
            ORDER_HAS_NO_ITEMS,
        )
