'use client';

import { Space, Tag, Typography } from 'antd';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatCount, formatRate } from '@/lib/number';
import { DEAL_STAGE } from '@/shared/constants';
import type { DealFunnelReport } from '../analytics.types';
import {
  CHART_GRID_COLOR,
  CHART_TEXT_COLOR,
  ExportButton,
  ReportCard,
  chartAmount,
  formatAmount,
  statusChartColor,
} from './report-card';

const COUNT_NAME = 'Угод';
const AMOUNT_NAME = 'Сума';

const CHART_HEIGHT = 280;
const STAGE_LABEL_WIDTH = 110;

interface DealFunnelChartProps {
  readonly report: DealFunnelReport | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly onExport: () => void;
  readonly isExporting: boolean;
}

export function DealFunnelChart({
  report,
  isLoading,
  isError,
  onExport,
  isExporting,
}: DealFunnelChartProps) {
  const stages = report?.stages ?? [];

  const data = stages.map((stage) => ({
    label: DEAL_STAGE[stage.stage].label,
    fill: statusChartColor(DEAL_STAGE[stage.stage].color),
    count: stage.count,
    amount: chartAmount(stage.amount),
  }));

  // A funnel with nothing in it is not a shape worth drawing.
  const isEmpty = data.every((row) => row.count === 0);

  return (
    <ReportCard
      title="Воронка угод"
      description="Скільки угод дійшло до кожної стадії та на яку суму"
      extra={<ExportButton onExport={onExport} isExporting={isExporting} />}
      isLoading={isLoading}
      isError={isError}
      isEmpty={data.length === 0 || isEmpty}
    >
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            allowDecimals={false}
            tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={STAGE_LABEL_WIDTH}
            tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }}
          />
          <Tooltip
            formatter={(value: unknown, name: unknown) =>
              name === AMOUNT_NAME ? formatAmount(Number(value)) : formatCount(Number(value))
            }
          />
          <Bar dataKey="count" name={COUNT_NAME} radius={[0, 4, 4, 0]}>
            {data.map((row) => (
              <Cell key={row.label} fill={row.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-3">
        <Typography.Text type="secondary">Переходи між стадіями</Typography.Text>
        <div className="mt-2">
          <Space wrap size={[8, 8]}>
            {(report?.conversions ?? []).map((conversion) => (
              <Tag
                key={`${conversion.from}-${conversion.to}`}
                color={DEAL_STAGE[conversion.to].color}
              >
                {DEAL_STAGE[conversion.from].label} → {DEAL_STAGE[conversion.to].label}:{' '}
                {formatRate(conversion.rate)}
              </Tag>
            ))}
          </Space>
        </div>
      </div>
    </ReportCard>
  );
}
