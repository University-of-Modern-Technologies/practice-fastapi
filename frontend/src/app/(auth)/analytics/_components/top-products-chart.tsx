'use client';

import { Segmented, Space } from 'antd';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatCount } from '@/lib/number';
import type { TopProductsReport } from '../analytics.types';
import { LIMIT_CHOICES } from '../analytics.validation';
import {
  CHART_COLORS,
  CHART_GRID_COLOR,
  CHART_TEXT_COLOR,
  ExportButton,
  ReportCard,
  chartAmount,
  formatAmount,
} from './report-card';

const REVENUE_NAME = 'Виручка';

const ROW_HEIGHT = 32;
const MIN_HEIGHT = 240;
const NAME_WIDTH = 180;
const MAX_NAME_LENGTH = 24;

/** Keeps a long catalogue name from eating the plotting area on a narrow screen. */
const shorten = (name: string): string =>
  name.length > MAX_NAME_LENGTH ? `${name.slice(0, MAX_NAME_LENGTH - 1)}…` : name;

interface TopProductsChartProps {
  readonly report: TopProductsReport | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly limit: number;
  readonly onLimitChange: (limit: number) => void;
  readonly onExport: () => void;
  readonly isExporting: boolean;
}

export function TopProductsChart({
  report,
  isLoading,
  isError,
  limit,
  onLimitChange,
  onExport,
  isExporting,
}: TopProductsChartProps) {
  const data = (report?.items ?? []).map((item) => ({
    label: shorten(item.name),
    sku: item.sku,
    quantity: item.quantity,
    revenue: chartAmount(item.revenue),
  }));

  return (
    <ReportCard
      title="Топ товарів"
      description="Товари з найбільшою виручкою за обраний період"
      extra={
        <Space size={8} wrap>
          <Segmented<number>
            size="small"
            value={limit}
            onChange={onLimitChange}
            options={LIMIT_CHOICES.map((value) => ({ value, label: String(value) }))}
          />
          <ExportButton onExport={onExport} isExporting={isExporting} />
        </Space>
      }
      isLoading={isLoading}
      isError={isError}
      isEmpty={data.length === 0}
    >
      <ResponsiveContainer
        width="100%"
        height={Math.max(MIN_HEIGHT, data.length * ROW_HEIGHT + MIN_HEIGHT / 4)}
      >
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }}
            tickFormatter={(value: unknown) => formatAmount(Number(value))}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={NAME_WIDTH}
            tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }}
          />
          <Tooltip
            formatter={(value: unknown, name: unknown) =>
              name === REVENUE_NAME ? formatAmount(Number(value)) : formatCount(Number(value))
            }
            labelFormatter={(
              label: unknown,
              payload: readonly { payload?: { sku?: string } }[],
            ) => {
              const sku = payload[0]?.payload?.sku;
              return sku ? `${String(label)} · ${sku}` : String(label);
            }}
          />
          <Bar
            dataKey="revenue"
            name={REVENUE_NAME}
            fill={CHART_COLORS.primary}
            radius={[0, 4, 4, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </ReportCard>
  );
}
