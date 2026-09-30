"""Vocabulary of the analytics module.

The query objects here are the *normalised* form of a request: a range is always
a resolved half-open interval, a limit is always a bounded integer. Everything
that turns a raw query string into one of these lives in ``schemas.py``, so the
service is never handed a value it still has to defend against.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.db.enums import DealStage, PermissionScope

__all__ = [
    "ANALYTICS_RESOURCE",
    "DEAL_FUNNEL_REPORT",
    "DEFAULT_ANALYTICS_TTL_SECONDS",
    "FUNNEL_PIPELINE",
    "OWNER_PERFORMANCE_REPORT",
    "SALES_SUMMARY_REPORT",
    "STOCK_HEALTH_REPORT",
    "TOP_PRODUCTS_REPORT",
    "AnalyticsAccess",
    "AnalyticsCache",
    "AnalyticsPeriod",
    "DealFunnelQuery",
    "NoopAnalyticsCache",
    "OwnerPerformanceQuery",
    "SalesSummaryQuery",
    "StockHealthQuery",
    "TopProductsQuery",
]

#: Permission resource guarding every report in this module.
ANALYTICS_RESOURCE = "analytics"

#: Report names, which are also the middle segment of every cache key.
SALES_SUMMARY_REPORT = "sales-summary"
DEAL_FUNNEL_REPORT = "deal-funnel"
TOP_PRODUCTS_REPORT = "top-products"
OWNER_PERFORMANCE_REPORT = "owner-performance"
STOCK_HEALTH_REPORT = "stock-health"

#: These are the slow queries of the system, so every report is cached.
#:
#: Invalidation is deliberately coarse: every successful write drops the whole
#: analytics namespace (see ``app.middleware.cache_invalidation``). The write
#: path would otherwise have to know which report each change moves, across key
#: spaces built from caller-chosen date ranges. The TTL is then only a backstop
#: for changes that bypass the API.
#: Fallback only; the wiring passes the configured cache TTL instead.
DEFAULT_ANALYTICS_TTL_SECONDS = 300


class AnalyticsPeriod(enum.StrEnum):
    """Bucket width of a time series."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


#: Conversion is measured along the winning pipeline only; ``LOST`` is a terminal
#: stage and is reported as a bucket, never as a step.
FUNNEL_PIPELINE: tuple[DealStage, ...] = (
    DealStage.LEAD,
    DealStage.QUALIFIED,
    DealStage.PROPOSAL,
    DealStage.WON,
)


@dataclass(frozen=True, slots=True)
class AnalyticsAccess:
    """Who is reading a report, and how broad their grant is.

    A report aggregates across owners, so there is no single owner a narrower
    grant could be measured against: the scope is carried for the audit of the
    decision, and the router admits nothing below ``ALL``.
    """

    actor_id: uuid.UUID
    scope: PermissionScope


@dataclass(frozen=True, slots=True)
class SalesSummaryQuery:
    """Normalised query of ``GET /analytics/sales-summary``."""

    from_: datetime
    to: datetime
    period: AnalyticsPeriod
    owner_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class DealFunnelQuery:
    """Normalised query of ``GET /analytics/deal-funnel``."""

    from_: datetime
    to: datetime
    owner_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class TopProductsQuery:
    """Normalised query of ``GET /analytics/top-products``."""

    from_: datetime
    to: datetime
    limit: int


@dataclass(frozen=True, slots=True)
class OwnerPerformanceQuery:
    """Normalised query of ``GET /analytics/owner-performance``."""

    from_: datetime
    to: datetime
    limit: int


@dataclass(frozen=True, slots=True)
class StockHealthQuery:
    """Normalised query of ``GET /analytics/stock-health``."""

    threshold: int
    limit: int
    warehouse_id: uuid.UUID | None = None


class AnalyticsCache(Protocol):
    """The slice of a cache backend this module needs.

    Only ``remember`` appears: reporting never writes, the drop after a write
    belongs to the middleware, and a read-through is the whole of the
    interaction.
    """

    async def remember[T](
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[T]],
    ) -> T: ...


class NoopAnalyticsCache:
    """Cache that stores nothing.

    The default whenever no backend is wired in, so that a missing cache is a
    performance property rather than a branch every call site has to handle.
    """

    async def remember[T](
        self,
        key: str,  # noqa: ARG002
        ttl_seconds: int,  # noqa: ARG002
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        return await loader()


#: Anything a cached report can be rebuilt from: a plain JSON document.
CachedReport = dict[str, Any]
