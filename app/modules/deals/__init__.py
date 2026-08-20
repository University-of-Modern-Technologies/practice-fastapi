"""Deals: the sales pipeline and the machine that moves a deal along it.

The stage is server-owned. It changes through one endpoint, under one set of
rules, recorded in the audit trail every time — which is what makes the pipeline
a fact about the business rather than a field the client happens to set.
"""

from __future__ import annotations

from app.modules.deals.router import DealsServiceDep, create_deals_router, get_deals_service
from app.modules.deals.schemas import (
    CreateDealRequest,
    DealListParams,
    DealOut,
    TransitionDealRequest,
    UpdateDealRequest,
)
from app.modules.deals.service import DealsService, to_deal_out
from app.modules.deals.transition import (
    ALLOWED_DEAL_STAGE_TRANSITIONS,
    assert_deal_probability,
    assert_deal_stage_transition,
    can_transition_deal_stage,
    is_terminal_deal_stage,
)
from app.modules.deals.types import DealAccess

__all__ = [
    "ALLOWED_DEAL_STAGE_TRANSITIONS",
    "CreateDealRequest",
    "DealAccess",
    "DealListParams",
    "DealOut",
    "DealsService",
    "DealsServiceDep",
    "TransitionDealRequest",
    "UpdateDealRequest",
    "assert_deal_probability",
    "assert_deal_stage_transition",
    "can_transition_deal_stage",
    "create_deals_router",
    "get_deals_service",
    "is_terminal_deal_stage",
    "to_deal_out",
]
