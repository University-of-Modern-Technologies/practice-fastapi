'use client';

import { Button, Col, Row, Space, Typography } from 'antd';
import { useEffect } from 'react';
import { DateRangeFilter, ModuleUnavailable, PageHeader, PermissionGate } from '@/components';
import { useReportError } from '@/shared/hooks';
import {
  DealFunnelChart,
  OwnerPerformanceTable,
  SalesSummaryChart,
  StockHealthTable,
  TopProductsChart,
} from './_components';
import { useAnalyticsRange } from './_hooks';
import {
  useDealFunnel,
  useExportReport,
  useOwnerPerformance,
  useSalesSummary,
  useStockHealth,
  useTopProducts,
} from './analytics.queries';
import { AnalyticsService, isModuleUnavailable } from './analytics.service';

export default function AnalyticsPage() {
  const range = useAnalyticsRange();
  const reportError = useReportError();

  // A window the API would reject is never sent: the user reads the reason under
  // the picker instead of five identical 400s.
  const enabled = range.issue === null;
  const wire = range.wire;

  const salesSummary = useSalesSummary({ ...wire, period: range.period }, { enabled });
  const dealFunnel = useDealFunnel(wire, { enabled });
  const topProducts = useTopProducts({ ...wire, limit: range.limit }, { enabled });
  const ownerPerformance = useOwnerPerformance({ ...wire, limit: range.limit }, { enabled });
  const stockHealth = useStockHealth(
    {
      threshold: range.stockThreshold,
      limit: range.stockLimit,
      ...(range.warehouseId ? { warehouseId: range.warehouseId } : {}),
    },
    { enabled: true },
  );

  const salesSummaryQuery = { ...wire, period: range.period };
  const dealFunnelQuery = wire;
  const topProductsQuery = { ...wire, limit: range.limit };
  const ownerPerformanceQuery = { ...wire, limit: range.limit };
  const stockHealthQuery = {
    threshold: range.stockThreshold,
    limit: range.stockLimit,
    ...(range.warehouseId ? { warehouseId: range.warehouseId } : {}),
  };

  // Each export is bound to the exact query its own card is showing right
  // now — the file that lands on disk can never drift from the numbers on
  // screen, because both come from the same object.
  const exportSalesSummary = useExportReport(
    (signal) => AnalyticsService.exportSalesSummary(salesSummaryQuery, signal),
    'sales-summary.csv',
  );
  const exportDealFunnel = useExportReport(
    (signal) => AnalyticsService.exportDealFunnel(dealFunnelQuery, signal),
    'deal-funnel.csv',
  );
  const exportTopProducts = useExportReport(
    (signal) => AnalyticsService.exportTopProducts(topProductsQuery, signal),
    'top-products.csv',
  );
  const exportOwnerPerformance = useExportReport(
    (signal) => AnalyticsService.exportOwnerPerformance(ownerPerformanceQuery, signal),
    'owner-performance.csv',
  );
  const exportStockHealth = useExportReport(
    (signal) => AnalyticsService.exportStockHealth(stockHealthQuery, signal),
    'stock-health.csv',
  );

  const results = [salesSummary, dealFunnel, topProducts, ownerPerformance, stockHealth];

  // Reporting may simply not be part of the API build the client is talking to.
  // That is an answer about the whole section, not a failure of one card.
  const unavailable = results.some((result) => isModuleUnavailable(result.error));

  const failure = results.find(
    (result) => result.isError && !isModuleUnavailable(result.error),
  )?.error;

  useEffect(() => {
    if (failure) reportError(failure);
  }, [failure, reportError]);

  return (
    <PermissionGate resource="analytics" action="read">
      <PageHeader
        title="Аналітика"
        description="Звіти за продажами, угодами, товарами та запасами"
        actions={
          <Space wrap>
            <DateRangeFilter
              from={range.calendar.from}
              to={range.calendar.to}
              onCommit={({ from, to }) => range.setParams({ from, to })}
            />
            <Button onClick={range.resetParams}>Скинути</Button>
          </Space>
        }
      />

      {range.issue ? (
        <Typography.Text type="danger" className="mb-4 block">
          {range.issue}
        </Typography.Text>
      ) : null}

      {unavailable ? (
        <ModuleUnavailable missing="звіти аналітики" requirement="аналітика потрібна" />
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24}>
            <SalesSummaryChart
              report={salesSummary.data}
              isLoading={salesSummary.isPending && enabled}
              isError={salesSummary.isError}
              period={range.period}
              onPeriodChange={(period) => range.setParams({ period })}
              onExport={() => exportSalesSummary.mutate()}
              isExporting={exportSalesSummary.isPending}
            />
          </Col>

          <Col xs={24} xl={12}>
            <DealFunnelChart
              report={dealFunnel.data}
              isLoading={dealFunnel.isPending && enabled}
              isError={dealFunnel.isError}
              onExport={() => exportDealFunnel.mutate()}
              isExporting={exportDealFunnel.isPending}
            />
          </Col>

          <Col xs={24} xl={12}>
            <TopProductsChart
              report={topProducts.data}
              isLoading={topProducts.isPending && enabled}
              isError={topProducts.isError}
              limit={range.limit}
              onLimitChange={(limit) => range.setParams({ limit })}
              onExport={() => exportTopProducts.mutate()}
              isExporting={exportTopProducts.isPending}
            />
          </Col>

          <Col xs={24}>
            <OwnerPerformanceTable
              report={ownerPerformance.data}
              isLoading={ownerPerformance.isPending && enabled}
              isError={ownerPerformance.isError}
              limit={range.limit}
              onLimitChange={(limit) => range.setParams({ limit })}
              onExport={() => exportOwnerPerformance.mutate()}
              isExporting={exportOwnerPerformance.isPending}
            />
          </Col>

          <Col xs={24}>
            <StockHealthTable
              report={stockHealth.data}
              isLoading={stockHealth.isPending}
              isError={stockHealth.isError}
              threshold={range.stockThreshold}
              limit={range.stockLimit}
              onThresholdChange={(threshold) => range.setParams({ stockThreshold: threshold })}
              onLimitChange={(stockLimit) => range.setParams({ stockLimit })}
              onExport={() => exportStockHealth.mutate()}
              isExporting={exportStockHealth.isPending}
            />
          </Col>
        </Row>
      )}
    </PermissionGate>
  );
}
