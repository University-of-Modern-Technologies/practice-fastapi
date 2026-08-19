"""HTTP surface of the reports.

Reporting is read-only, and that is a property of the router as much as of the
service: there is no write handler here, so no report can be added later that
quietly mutates something.

The permission is required by a dependency every handler shares rather than
repeated per route, so a sixth report cannot be published without a check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.core.errors import ValidationFailedError
from app.core.responses import Envelope
from app.db.enums import PermissionScope
from app.modules.analytics.export import ANALYTICS_EXPORT_DESCRIPTORS, EXPORT_FORMATS, render_csv
from app.modules.analytics.schemas import (
    DealFunnelParams,
    DealFunnelReport,
    OwnerPerformanceParams,
    OwnerPerformanceReport,
    SalesSummaryParams,
    SalesSummaryReport,
    StockHealthParams,
    StockHealthReport,
    TopProductsParams,
    TopProductsReport,
)
from app.modules.analytics.service import AnalyticsService
from app.modules.analytics.types import (
    ANALYTICS_RESOURCE,
    AnalyticsAccess,
    AnalyticsCache,
)
from app.modules.auth.dependencies import CurrentAuth, SessionDep, SettingsDep
from app.modules.rbac.dependencies import CacheDep, ensure_scope_all, require_permission

RESOURCE = ANALYTICS_RESOURCE


def get_analytics_cache(cache: CacheDep) -> AnalyticsCache:
    """The wired cache backend, seen through the narrow port this module needs.

    The shared backend already offers a read-through; describing it structurally
    is what keeps reporting compilable and testable without one.
    """
    return cache


AnalyticsCacheDep = Annotated[AnalyticsCache, Depends(get_analytics_cache)]


def get_analytics_service(
    session: SessionDep, cache: AnalyticsCacheDep, settings: SettingsDep
) -> AnalyticsService:
    # The report TTL is the shared cache TTL, so an operator can trade freshness
    # against database load from configuration instead of from a code change.
    return AnalyticsService(session, cache, settings.cache_ttl_seconds)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


def _require_read_access() -> Callable[..., Awaitable[AnalyticsAccess]]:
    """Builds the dependency that admits a caller and describes them."""
    permission = require_permission(RESOURCE, "read")

    # The permission is a default rather than an ``Annotated`` member: postponed
    # annotations turn every hint into a string, and a string naming a local
    # closure is not something FastAPI can resolve at import.
    async def dependency(
        auth: CurrentAuth,
        scope: PermissionScope = Depends(permission),
    ) -> AnalyticsAccess:
        # Every report aggregates across owners, so there is no single owner a
        # narrower grant could be measured against. A holder of ``OWN`` is
        # refused rather than served a report silently narrowed to themselves,
        # which would look like the organization's figures and would not be.
        ensure_scope_all(scope)
        return AnalyticsAccess(actor_id=auth.user_id, scope=scope)

    return dependency


ReadAccess = Annotated[AnalyticsAccess, Depends(_require_read_access())]

SalesSummaryQueryParams = Annotated[SalesSummaryParams, Query()]
DealFunnelQueryParams = Annotated[DealFunnelParams, Query()]
TopProductsQueryParams = Annotated[TopProductsParams, Query()]
OwnerPerformanceQueryParams = Annotated[OwnerPerformanceParams, Query()]
StockHealthQueryParams = Annotated[StockHealthParams, Query()]


def create_analytics_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Analytics"])

    @router.get("/sales-summary", summary="Виторг за періодами")
    async def sales_summary(
        _access: ReadAccess,
        service: AnalyticsServiceDep,
        params: SalesSummaryQueryParams,
    ) -> Envelope[SalesSummaryReport]:
        return Envelope(data=await service.sales_summary(params.to_query()))

    @router.get("/deal-funnel", summary="Воронка угод та конверсія між стадіями")
    async def deal_funnel(
        _access: ReadAccess,
        service: AnalyticsServiceDep,
        params: DealFunnelQueryParams,
    ) -> Envelope[DealFunnelReport]:
        return Envelope(data=await service.deal_funnel(params.to_query()))

    @router.get("/top-products", summary="Товари з найбільшим виторгом")
    async def top_products(
        _access: ReadAccess,
        service: AnalyticsServiceDep,
        params: TopProductsQueryParams,
    ) -> Envelope[TopProductsReport]:
        return Envelope(data=await service.top_products(params.to_query()))

    @router.get("/owner-performance", summary="Результати менеджерів")
    async def owner_performance(
        _access: ReadAccess,
        service: AnalyticsServiceDep,
        params: OwnerPerformanceQueryParams,
    ) -> Envelope[OwnerPerformanceReport]:
        return Envelope(data=await service.owner_performance(params.to_query()))

    @router.get("/stock-health", summary="Залишки нижче порогу")
    async def stock_health(
        _access: ReadAccess,
        service: AnalyticsServiceDep,
        params: StockHealthQueryParams,
    ) -> Envelope[StockHealthReport]:
        return Envelope(data=await service.stock_health(params.to_query()))

    # One handler for all five reports: the descriptor named by `{report}`
    # supplies the query model, the service call and the column order, so a
    # sixth report needs a new descriptor entry and nothing here. The
    # permission dependency is the same one guarding the report itself, since
    # `{report}` can only ever name one of the five already gated above.
    @router.get("/{report}/export", summary="Вивантаження звіту, csv чи json")
    async def export_report(
        report: str,
        _access: ReadAccess,
        service: AnalyticsServiceDep,
        request: Request,
    ) -> Response:
        descriptor = ANALYTICS_EXPORT_DESCRIPTORS.get(report)
        if descriptor is None:
            raise ValidationFailedError(
                details={
                    "formErrors": [],
                    "fieldErrors": {"report": [f'Unknown report "{report}"']},
                }
            )

        raw_query = dict(request.query_params)
        format_value = raw_query.pop("format", "csv")
        if format_value not in EXPORT_FORMATS:
            raise ValidationFailedError(
                details={
                    "formErrors": [],
                    "fieldErrors": {"format": [f'Unknown format "{format_value}"']},
                }
            )

        rows = await descriptor.load_rows(service, raw_query)

        if format_value == "json":
            return JSONResponse({"data": rows})

        return Response(
            content=render_csv(descriptor.columns, rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{descriptor.file_stem}.csv"'},
        )

    return router
