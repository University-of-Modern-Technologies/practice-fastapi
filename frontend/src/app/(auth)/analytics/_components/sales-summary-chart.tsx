'use client';

import { Col, Row, Segmented, Space, Statistic } from 'antd';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { DateTime } from '@/lib/date-time';
import { formatCount } from '@/lib/number';
import {
  ANALYTICS_PERIODS,
  type AnalyticsPeriod,
  type SalesSummaryReport,
} from '../analytics.types';
import {
  CHART_COLORS,
  CHART_GRID_COLOR,
  CHART_TEXT_COLOR,
  ExportButton,
  ReportCard,
  chartAmount,
  formatAmount,
} from './report-card';

const PERIOD_LABELS: Readonly<Record<AnalyticsPeriod, string>> = {
  day: 'День',
  week: 'Тиждень',
  month: 'Місяць',
};

const REVENUE_NAME = 'Виручка';
const ORDERS_NAME = 'Замовлення';

const CHART_HEIGHT = 280;

interface SalesSummaryChartProps {
  readonly report: SalesSummaryReport | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly period: AnalyticsPeriod;
  readonly onPeriodChange: (period: AnalyticsPeriod) => void;
  readonly onExport: () => void;
  readonly isExporting: boolean;
}

export function SalesSummaryChart({
  report,
  isLoading,
  isError,
  period,
  onPeriodChange,
  onExport,
  isExporting,
}: SalesSummaryChartProps) {
  // The bucket label is prepared once per row: recharts would otherwise call the
  // formatter again for the axis, the tooltip and every label of the same point.
  const data = (report?.series ?? []).map((bucket) => ({
    label: DateTime.toDate(bucket.bucketStart),
    orderCount: bucket.orderCount,
    revenue: chartAmount(bucket.revenue),
  }));

  return (
    <ReportCard
      title="Продажі"
      description="Кількість замовлень і виручка за обраний період"
      extra={
        <Space size={8} wrap>
          <Segmented<AnalyticsPeriod>
            size="small"
            value={period}
            onChange={onPeriodChange}
            options={ANALYTICS_PERIODS.map((value) => ({
              value,
              label: PERIOD_LABELS[value],
            }))}
          />
          <ExportButton onExport={onExport} isExporting={isExporting} />
        </Space>
      }
      isLoading={isLoading}
      isError={isError}
      isEmpty={data.length === 0}
    >
      <Row gutter={[16, 8]} className="mb-4">
        <Col xs={24} sm={8}>
          <Statistic title="Замовлень" value={report?.totals.orderCount ?? 0} />
        </Col>
        <Col xs={24} sm={8}>
          <Statistic
            title="Виручка"
            // Already formatted through Money — recharts and antd both receive a string.
            value={formatAmount(report?.totals.revenue ?? '0.00')}
          />
        </Col>
        <Col xs={24} sm={8}>
          <Statistic
            title="Середній чек"
            value={formatAmount(report?.totals.averageOrderValue ?? '0.00')}
          />
        </Col>
      </Row>

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }} />
          <YAxis
            yAxisId="orders"
            allowDecimals={false}
            tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }}
          />
          <YAxis
            yAxisId="revenue"
            orientation="right"
            tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }}
            tickFormatter={(value: unknown) => formatAmount(Number(value))}
          />
          <Tooltip
            formatter={(value: unknown, name: unknown) =>
              name === REVENUE_NAME ? formatAmount(Number(value)) : formatCount(Number(value))
            }
          />
          <Legend />
          <Bar
            yAxisId="orders"
            dataKey="orderCount"
            name={ORDERS_NAME}
            fill={CHART_COLORS.info}
            radius={[4, 4, 0, 0]}
          />
          <Line
            yAxisId="revenue"
            type="monotone"
            dataKey="revenue"
            name={REVENUE_NAME}
            stroke={CHART_COLORS.primary}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ReportCard>
  );
}
