"""Analytics: five aggregate reports over the operational tables.

Mount with ``create_analytics_router()`` under ``/api/v1/analytics``. Nothing in
this module writes, and every report is served through a short-lived cache.
"""

from __future__ import annotations

from app.modules.analytics.cache_keys import (
    ANALYTICS_NAMESPACE,
    analytics_prefix,
    analytics_report_key,
)
from app.modules.analytics.decimal import (
    MONEY_SCALE,
    average_decimal,
    compare_decimals,
    format_decimal,
    from_scaled_integer,
    ratio,
    sum_decimals,
    to_scaled_integer,
)
from app.modules.analytics.export import (
    ANALYTICS_EXPORT_DESCRIPTORS,
    EXPORT_FORMATS,
    AnalyticsExportDescriptor,
    render_csv,
)
from app.modules.analytics.router import (
    create_analytics_router,
    get_analytics_service,
)
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
    DEFAULT_ANALYTICS_TTL_SECONDS,
    AnalyticsAccess,
    AnalyticsCache,
    AnalyticsPeriod,
    DealFunnelQuery,
    NoopAnalyticsCache,
    OwnerPerformanceQuery,
    SalesSummaryQuery,
    StockHealthQuery,
    TopProductsQuery,
)

__all__ = [
    "ANALYTICS_EXPORT_DESCRIPTORS",
    "ANALYTICS_NAMESPACE",
    "ANALYTICS_RESOURCE",
    "DEFAULT_ANALYTICS_TTL_SECONDS",
    "EXPORT_FORMATS",
    "MONEY_SCALE",
    "AnalyticsAccess",
    "AnalyticsCache",
    "AnalyticsExportDescriptor",
    "AnalyticsPeriod",
    "AnalyticsService",
    "DealFunnelParams",
    "DealFunnelQuery",
    "DealFunnelReport",
    "NoopAnalyticsCache",
    "OwnerPerformanceParams",
    "OwnerPerformanceQuery",
    "OwnerPerformanceReport",
    "SalesSummaryParams",
    "SalesSummaryQuery",
    "SalesSummaryReport",
    "StockHealthParams",
    "StockHealthQuery",
    "StockHealthReport",
    "TopProductsParams",
    "TopProductsQuery",
    "TopProductsReport",
    "analytics_prefix",
    "analytics_report_key",
    "average_decimal",
    "compare_decimals",
    "create_analytics_router",
    "format_decimal",
    "from_scaled_integer",
    "get_analytics_service",
    "ratio",
    "render_csv",
    "sum_decimals",
    "to_scaled_integer",
]
