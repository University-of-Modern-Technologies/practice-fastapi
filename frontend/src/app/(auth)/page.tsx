'use client';

import { Col, Row, Typography } from 'antd';
import Link from 'next/link';
import { MoneyValue, PageHeader } from '@/components';
import { useHasPermission } from '@/shared/hooks';
import { useAuthStore } from '@/shared/stores';
import { DealFunnelSummary, LowStockSummary, MetricCard, QuickLinks } from './_components';
import {
  DASHBOARD_RANGE_LABEL,
  LOW_STOCK_THRESHOLD,
  useDealFunnel,
  useSalesSummary,
  useStockHealth,
} from './dashboard.queries';

const PERIOD_HINT = `За ${DASHBOARD_RANGE_LABEL}`;

export default function DashboardPage() {
  const user = useAuthStore((state) => state.user);

  const canReadAnalytics = useHasPermission('analytics', 'read');
  const canReadWarehouse = useHasPermission('warehouse', 'read');

  // Stock health is served by the analytics module, so it needs both grants:
  // warehouse access decides whether the block belongs on this page at all,
  // analytics access decides whether the request can succeed.
  const summary = useSalesSummary(canReadAnalytics);
  const funnel = useDealFunnel(canReadAnalytics);
  const stock = useStockHealth(canReadWarehouse && canReadAnalytics);

  const showMetrics = canReadAnalytics && !summary.isUnavailable;
  const showFunnel = canReadAnalytics && !funnel.isUnavailable;
  const showStock = canReadWarehouse && canReadAnalytics && !stock.isUnavailable;
  const totals = summary.data?.totals;

  return (
    <>
      <PageHeader
        title={`Вітаємо, ${user?.name ?? ''}`}
        description="Стан справ і розділи, доступні вашій ролі"
      />

      {showMetrics ? (
        <section className="mb-6">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <Typography.Title level={5} style={{ margin: 0 }}>
              Показники
            </Typography.Title>
            <Link href="/analytics">Детальніше</Link>
          </div>

          <Row gutter={[16, 16]}>
            <Col xs={24} sm={12} xl={8}>
              <MetricCard
                label="Замовлень"
                hint={PERIOD_HINT}
                isLoading={summary.isLoading}
                value={<span className="numeric">{totals?.orderCount ?? 0}</span>}
              />
            </Col>
            <Col xs={24} sm={12} xl={8}>
              <MetricCard
                label="Виручка"
                hint={PERIOD_HINT}
                isLoading={summary.isLoading}
                value={<MoneyValue value={totals?.revenue} showCurrency />}
              />
            </Col>
            <Col xs={24} sm={12} xl={8}>
              <MetricCard
                label="Середній чек"
                hint={PERIOD_HINT}
                isLoading={summary.isLoading}
                value={<MoneyValue value={totals?.averageOrderValue} showCurrency />}
              />
            </Col>
          </Row>
        </section>
      ) : null}

      {showFunnel || showStock ? (
        <Row gutter={[16, 16]} className="mb-6">
          {showFunnel ? (
            <Col xs={24} lg={12}>
              <DealFunnelSummary stages={funnel.data?.stages} isLoading={funnel.isLoading} />
            </Col>
          ) : null}
          {showStock ? (
            <Col xs={24} lg={12}>
              <LowStockSummary
                rows={stock.data?.items}
                threshold={stock.data?.threshold ?? LOW_STOCK_THRESHOLD}
                isLoading={stock.isLoading}
              />
            </Col>
          ) : null}
        </Row>
      ) : null}

      <section>
        <Typography.Title level={5} style={{ marginBottom: 12 }}>
          Швидкі переходи
        </Typography.Title>
        <QuickLinks />
      </section>
    </>
  );
}
