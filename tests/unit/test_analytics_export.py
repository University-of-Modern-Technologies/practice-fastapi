"""HTTP contract of `GET /analytics/{report}/export`.

RBAC and authentication are replaced by doubles, and the analytics service
by a stub that returns fixed reports, so these tests are about the export
surface itself: CSV escaping, the money figures matching the JSON a report
would print, the empty-table case, and the validation envelope for a bad
report or format name.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.settings import Settings
from app.db.enums import DealStage, PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.analytics.router import create_analytics_router, get_analytics_service
from app.modules.analytics.schemas import (
    DealFunnelConversion,
    DealFunnelReport,
    DealFunnelStage,
    OwnerPerformanceReport,
    OwnerPerformanceRow,
    SalesSummaryBucket,
    SalesSummaryReport,
    SalesSummaryTotals,
    StockHealthReport,
    StockHealthRow,
    TopProductRow,
    TopProductsReport,
)
from app.modules.analytics.types import AnalyticsPeriod
from app.modules.auth.dependencies import get_auth
from app.modules.auth.types import AuthContext
from app.modules.rbac.dependencies import get_rbac_service

USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000001")

FROM = "2026-01-01T00:00:00.000Z"
TO = "2026-01-31T00:00:00.000Z"

EMPTY_SALES_SUMMARY = SalesSummaryReport(
    from_=FROM,  # type: ignore[arg-type]
    to=TO,  # type: ignore[arg-type]
    period=AnalyticsPeriod.DAY,
    totals=SalesSummaryTotals(order_count=0, revenue="0.00", average_order_value="0.00"),
    series=[],
)

SALES_SUMMARY_WITH_ROWS = EMPTY_SALES_SUMMARY.model_copy(
    update={
        "series": [
            SalesSummaryBucket(bucket_start=FROM, order_count=2, revenue="1234.50"),  # type: ignore[arg-type]
            SalesSummaryBucket(
                bucket_start="2026-01-02T00:00:00.000Z",  # type: ignore[arg-type]
                order_count=1,
                revenue="0.00",
            ),
        ]
    }
)

DEAL_FUNNEL_REPORT = DealFunnelReport(
    from_=FROM,  # type: ignore[arg-type]
    to=TO,  # type: ignore[arg-type]
    stages=[
        DealFunnelStage(stage=DealStage.LEAD, count=3, amount="900.00"),
        DealFunnelStage(stage=DealStage.QUALIFIED, count=2, amount="600.00"),
        DealFunnelStage(stage=DealStage.PROPOSAL, count=1, amount="300.00"),
        DealFunnelStage(stage=DealStage.WON, count=1, amount="300.00"),
        DealFunnelStage(stage=DealStage.LOST, count=0, amount="0.00"),
    ],
    conversions=[
        DealFunnelConversion(from_=DealStage.LEAD, to=DealStage.QUALIFIED, rate=0.6667),
        DealFunnelConversion(from_=DealStage.QUALIFIED, to=DealStage.PROPOSAL, rate=0.5),
        DealFunnelConversion(from_=DealStage.PROPOSAL, to=DealStage.WON, rate=1),
    ],
)

TOP_PRODUCTS_REPORT = TopProductsReport(
    from_=FROM,  # type: ignore[arg-type]
    to=TO,  # type: ignore[arg-type]
    limit=10,
    items=[
        TopProductRow(
            product_id=uuid.UUID("20000000-0000-4000-8000-000000000001"),
            sku="SKU-1",
            # A comma and a double quote, both requiring RFC 4180 quoting.
            name='Widget, "Deluxe"',
            quantity=5,
            revenue="499.99",
        )
    ],
)

OWNER_PERFORMANCE_REPORT = OwnerPerformanceReport(
    from_=FROM,  # type: ignore[arg-type]
    to=TO,  # type: ignore[arg-type]
    items=[
        OwnerPerformanceRow(
            owner_id=uuid.UUID("30000000-0000-4000-8000-000000000001"),
            name="Ada Lovelace",
            email="ada@example.com",
            deal_count=4,
            deal_amount="1000.00",
            won_deal_count=2,
            won_deal_amount="500.00",
            win_rate=0.5,
            order_count=3,
            order_revenue="750.25",
        )
    ],
)

STOCK_HEALTH_REPORT = StockHealthReport(
    threshold=5,
    limit=10,
    items=[
        StockHealthRow(
            product_id=uuid.UUID("20000000-0000-4000-8000-000000000001"),
            sku="SKU-1",
            name="Widget",
            warehouse_id=uuid.UUID("40000000-0000-4000-8000-000000000001"),
            warehouse_code="MAIN",
            quantity_on_hand=3,
            quantity_reserved=1,
            quantity_available=2,
        )
    ],
)


class FakeAnalyticsService:
    """Returns a fixed report per method; never touches a database."""

    async def sales_summary(self, _query: object) -> SalesSummaryReport:
        return SALES_SUMMARY_WITH_ROWS

    async def deal_funnel(self, _query: object) -> DealFunnelReport:
        return DEAL_FUNNEL_REPORT

    async def top_products(self, _query: object) -> TopProductsReport:
        return TOP_PRODUCTS_REPORT

    async def owner_performance(self, _query: object) -> OwnerPerformanceReport:
        return OWNER_PERFORMANCE_REPORT

    async def stock_health(self, _query: object) -> StockHealthReport:
        return STOCK_HEALTH_REPORT


@pytest.fixture
def analytics_app(settings: Settings) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=[("/api/v1/analytics", create_analytics_router())])
    app.state.settings = settings

    async def authenticated() -> AuthContext:
        return AuthContext(user_id=USER_ID, session_id=SESSION_ID)

    class GrantingRbac:
        async def get_permission_scope(
            self, _user_id: uuid.UUID, _resource: str, _action: str
        ) -> PermissionScope | None:
            return PermissionScope.ALL

    app.dependency_overrides[get_auth] = authenticated
    app.dependency_overrides[get_rbac_service] = GrantingRbac
    app.dependency_overrides[get_analytics_service] = FakeAnalyticsService
    return app


@pytest.fixture
async def analytics_client(analytics_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=analytics_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_exports_sales_summary_as_csv_with_money_matching_the_json_report(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get("/api/v1/analytics/sales-summary/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="sales-summary.csv"'
    assert response.text == (
        "bucketStart,orderCount,revenue\r\n"
        "2026-01-01T00:00:00.000Z,2,1234.50\r\n"
        "2026-01-02T00:00:00.000Z,1,0.00\r\n"
    )


async def test_defaults_to_csv_when_format_is_not_given(analytics_client: AsyncClient) -> None:
    response = await analytics_client.get("/api/v1/analytics/deal-funnel/export")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"


async def test_escapes_a_comma_and_a_double_quote_per_rfc_4180(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get("/api/v1/analytics/top-products/export")

    assert response.status_code == 200
    assert response.text == (
        "productId,sku,name,quantity,revenue\r\n"
        '20000000-0000-4000-8000-000000000001,SKU-1,"Widget, ""Deluxe""",5,499.99\r\n'
    )


async def test_an_empty_report_downloads_as_only_a_header_row(
    analytics_app: FastAPI, analytics_client: AsyncClient
) -> None:
    class EmptySalesSummaryService(FakeAnalyticsService):
        async def sales_summary(self, _query: object) -> SalesSummaryReport:
            return EMPTY_SALES_SUMMARY

    analytics_app.dependency_overrides[get_analytics_service] = EmptySalesSummaryService

    response = await analytics_client.get("/api/v1/analytics/sales-summary/export")

    assert response.status_code == 200
    assert response.text == "bucketStart,orderCount,revenue\r\n"


async def test_exports_as_json_with_the_same_money_strings_as_the_report(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get(
        "/api/v1/analytics/owner-performance/export", params={"format": "json"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "data": [
            {
                "ownerId": "30000000-0000-4000-8000-000000000001",
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "dealCount": 4,
                "dealAmount": "1000.00",
                "wonDealCount": 2,
                "wonDealAmount": "500.00",
                "winRate": 0.5,
                "orderCount": 3,
                "orderRevenue": "750.25",
            }
        ]
    }


async def test_an_unknown_report_name_is_a_validation_error(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get("/api/v1/analytics/not-a-report/export")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_an_unknown_format_is_a_validation_error(analytics_client: AsyncClient) -> None:
    response = await analytics_client.get(
        "/api/v1/analytics/stock-health/export", params={"format": "xml"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_the_report_specific_query_is_still_validated(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get(
        "/api/v1/analytics/top-products/export", params={"limit": 0}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_export_requires_the_same_permission_as_the_report(settings: Settings) -> None:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=[("/api/v1/analytics", create_analytics_router())])
    app.state.settings = settings

    async def authenticated() -> AuthContext:
        return AuthContext(user_id=USER_ID, session_id=SESSION_ID)

    class RefusingRbac:
        async def get_permission_scope(
            self, _user_id: uuid.UUID, _resource: str, _action: str
        ) -> PermissionScope | None:
            return None

    app.dependency_overrides[get_auth] = authenticated
    app.dependency_overrides[get_rbac_service] = RefusingRbac
    app.dependency_overrides[get_analytics_service] = FakeAnalyticsService

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/analytics/sales-summary/export")

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("report", "file_name"),
    [
        ("sales-summary", "sales-summary.csv"),
        ("deal-funnel", "deal-funnel.csv"),
        ("top-products", "top-products.csv"),
        ("owner-performance", "owner-performance.csv"),
        ("stock-health", "stock-health.csv"),
    ],
)
async def test_every_report_exports_as_a_downloadable_csv(
    analytics_client: AsyncClient, report: str, file_name: str
) -> None:
    response = await analytics_client.get(f"/api/v1/analytics/{report}/export")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="{file_name}"'
    assert response.text.split("\r\n")[0]


async def test_deal_funnel_export_carries_stage_rows_not_the_derived_conversions(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get("/api/v1/analytics/deal-funnel/export")

    assert response.text == (
        "stage,count,amount\r\n"
        "LEAD,3,900.00\r\n"
        "QUALIFIED,2,600.00\r\n"
        "PROPOSAL,1,300.00\r\n"
        "WON,1,300.00\r\n"
        "LOST,0,0.00\r\n"
    )


async def test_stock_health_export_carries_every_quantity_column(
    analytics_client: AsyncClient,
) -> None:
    response = await analytics_client.get("/api/v1/analytics/stock-health/export")

    assert response.text == (
        "productId,sku,name,warehouseId,warehouseCode,quantityOnHand,"
        "quantityReserved,quantityAvailable\r\n"
        "20000000-0000-4000-8000-000000000001,SKU-1,Widget,"
        "40000000-0000-4000-8000-000000000001,MAIN,3,1,2\r\n"
    )
