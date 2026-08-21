'use client';

import { Segmented, Space, Typography } from 'antd';
import { MoneyValue, SimpleTable, type DataTableColumns } from '@/components';
import { formatCount, formatRate } from '@/lib/number';
import type { OwnerPerformanceRow, OwnerPerformanceReport } from '../analytics.types';
import { LIMIT_CHOICES } from '../analytics.validation';
import { EMPTY_REPORT_TEXT, ExportButton, ReportCard } from './report-card';

const columns: DataTableColumns<OwnerPerformanceRow> = [
  {
    title: 'Менеджер',
    dataIndex: 'name',
    render: (_: unknown, row: OwnerPerformanceRow) => (
      <div>
        <div>{row.name ?? 'Без імені'}</div>
        {row.email ? <Typography.Text type="secondary">{row.email}</Typography.Text> : null}
      </div>
    ),
  },
  {
    title: 'Угод',
    dataIndex: 'dealCount',
    align: 'right',
    render: (value: number) => <span className="numeric">{formatCount(value)}</span>,
  },
  {
    title: 'Сума угод',
    dataIndex: 'dealAmount',
    align: 'right',
    render: (value: string) => <MoneyValue value={value} />,
  },
  {
    title: 'Виграно',
    dataIndex: 'wonDealCount',
    align: 'right',
    render: (value: number) => <span className="numeric">{formatCount(value)}</span>,
  },
  {
    title: 'Сума виграних',
    dataIndex: 'wonDealAmount',
    align: 'right',
    render: (value: string) => <MoneyValue value={value} />,
  },
  {
    title: 'Конверсія',
    dataIndex: 'winRate',
    align: 'right',
    // A share on the wire, a percentage on screen — the same rule as the funnel.
    render: (value: number) => <span className="numeric">{formatRate(value)}</span>,
  },
  {
    title: 'Замовлень',
    dataIndex: 'orderCount',
    align: 'right',
    render: (value: number) => <span className="numeric">{formatCount(value)}</span>,
  },
  {
    title: 'Виручка',
    dataIndex: 'orderRevenue',
    align: 'right',
    render: (value: string) => <MoneyValue value={value} />,
  },
];

interface OwnerPerformanceTableProps {
  readonly report: OwnerPerformanceReport | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly limit: number;
  readonly onLimitChange: (limit: number) => void;
  readonly onExport: () => void;
  readonly isExporting: boolean;
}

export function OwnerPerformanceTable({
  report,
  isLoading,
  isError,
  limit,
  onLimitChange,
  onExport,
  isExporting,
}: OwnerPerformanceTableProps) {
  const rows = report?.items ?? [];

  return (
    <ReportCard
      title="Ефективність менеджерів"
      description="Угоди та замовлення в розрізі власника за обраний період"
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
      isEmpty={false}
    >
      <SimpleTable<OwnerPerformanceRow>
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        rowKey="ownerId"
        emptyText={EMPTY_REPORT_TEXT}
      />
    </ReportCard>
  );
}
