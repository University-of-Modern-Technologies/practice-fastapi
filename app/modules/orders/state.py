"""The order lifecycle, gathered into one object per status.

Grouping the transition table, the editability rule and the stock effect
inside a single hierarchy is what keeps adding a status from being a change
that touches three unrelated files, only two of which a reviewer happens to
look at.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.db.enums import OrderStatus
from app.modules.orders.types import OrderStockEffect

__all__ = ["OrderState", "order_state"]


class OrderState(ABC):
    """One status of the order lifecycle, and everything that follows from it."""

    #: The status this object describes.
    status: OrderStatus
    #: Statuses reachable from here.
    allowed_transitions: tuple[OrderStatus, ...]
    #: Lines and monetary fields may only be reshaped in this state.
    is_editable: bool = False
    #: Leaving this state requires at least one line.
    requires_items: bool = False

    @abstractmethod
    def stock_effect(self, to_status: OrderStatus) -> OrderStockEffect | None:
        """Stock consequence of moving to ``to_status``, or ``None`` if any."""


class _Draft(OrderState):
    """Still being assembled: freely reshaped, but never left empty-handed.

    Confirming it is the moment the goods are promised to the buyer, so that
    is the one move out of here that reserves stock.
    """

    status = OrderStatus.DRAFT
    allowed_transitions = (OrderStatus.CONFIRMED, OrderStatus.CANCELLED)
    is_editable = True
    requires_items = True

    def stock_effect(self, to_status: OrderStatus) -> OrderStockEffect | None:
        return "reserve" if to_status is OrderStatus.CONFIRMED else None


class _Confirmed(OrderState):
    """Fixed in shape; cancelling it gives the reservation back."""

    status = OrderStatus.CONFIRMED
    allowed_transitions = (OrderStatus.PAID, OrderStatus.CANCELLED)

    def stock_effect(self, to_status: OrderStatus) -> OrderStockEffect | None:
        return "release" if to_status is OrderStatus.CANCELLED else None


class _Paid(OrderState):
    """Either the goods go out (fulfilment) or the reservation comes back
    (cancellation) — the only two moves left from here."""

    status = OrderStatus.PAID
    allowed_transitions = (OrderStatus.FULFILLED, OrderStatus.CANCELLED)

    def stock_effect(self, to_status: OrderStatus) -> OrderStockEffect | None:
        if to_status is OrderStatus.FULFILLED:
            return "issue"
        if to_status is OrderStatus.CANCELLED:
            return "release"
        return None


class _Fulfilled(OrderState):
    """Final: the goods have already left the warehouse."""

    status = OrderStatus.FULFILLED
    allowed_transitions = ()

    def stock_effect(self, to_status: OrderStatus) -> OrderStockEffect | None:  # noqa: ARG002
        return None


class _Cancelled(OrderState):
    """Final: whatever stock this order held has already been released."""

    status = OrderStatus.CANCELLED
    allowed_transitions = ()

    def stock_effect(self, to_status: OrderStatus) -> OrderStockEffect | None:  # noqa: ARG002
        return None


_STATES: dict[OrderStatus, OrderState] = {
    OrderStatus.DRAFT: _Draft(),
    OrderStatus.CONFIRMED: _Confirmed(),
    OrderStatus.PAID: _Paid(),
    OrderStatus.FULFILLED: _Fulfilled(),
    OrderStatus.CANCELLED: _Cancelled(),
}


def order_state(status: OrderStatus) -> OrderState:
    """The single object that knows everything about ``status``."""
    return _STATES[status]
