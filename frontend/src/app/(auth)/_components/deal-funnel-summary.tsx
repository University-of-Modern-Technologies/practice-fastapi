'use client';

import { Card } from 'antd';
import Link from 'next/link';
import { MoneyValue, SimpleTable, StatusTag, type DataTableColumns } from '@/components';
import { DEAL_STAGE } from '@/shared/constants';
import type { DealFunnelStage } from '../dashboard.types';

const COLUMNS: DataTableColumns<DealFunnelStage> = [
  {
    title: 'Стадія',
    dataIndex: 'stage',
    render: (stage: string) => <StatusTag dictionary={DEAL_STAGE} value={stage} />,
  },
  {
    title: 'Угод',
    dataIndex: 'count',
    align: 'right',
    render: (count: number) => <span className="numeric">{count}</span>,
  },
  {
    title: 'Сума',
    dataIndex: 'amount',
    align: 'right',
    render: (amount: string) => <MoneyValue value={amount} showCurrency />,
  },
];

interface DealFunnelSummaryProps {
  readonly stages: readonly DealFunnelStage[] | undefined;
  readonly isLoading: boolean;
}

/** Counts and sums per stage — the shape of the pipeline, not its history. */
export function DealFunnelSummary({ stages, isLoading }: DealFunnelSummaryProps) {
  return (
    <Card
      size="small"
      title="Воронка угод"
      extra={<Link href="/deals">Детальніше</Link>}
      styles={{ body: { padding: 0 } }}
    >
      <SimpleTable<DealFunnelStage>
        columns={COLUMNS}
        rows={stages}
        isLoading={isLoading}
        rowKey="stage"
        emptyText="За цей період угод не було"
      />
    </Card>
  );
}
