'use client';

import { Card, Typography } from 'antd';
import Link from 'next/link';
import { SimpleTable, type DataTableColumns } from '@/components';
import type { StockHealthRow } from '../dashboard.types';

const COLUMNS: DataTableColumns<StockHealthRow> = [
  {
    title: 'Товар',
    dataIndex: 'name',
    render: (name: string, row: StockHealthRow) => (
      <div className="flex flex-col">
        <Typography.Text>{name}</Typography.Text>
        <Typography.Text type="secondary" className="text-xs">
          {row.sku} · {row.warehouseCode}
        </Typography.Text>
      </div>
    ),
  },
  {
    title: 'Доступно',
    dataIndex: 'quantityAvailable',
    align: 'right',
    render: (quantity: number) => (
      <Typography.Text type={quantity <= 0 ? 'danger' : 'warning'} className="numeric">
        {quantity}
      </Typography.Text>
    ),
  },
];

interface LowStockSummaryProps {
  readonly rows: readonly StockHealthRow[] | undefined;
  readonly threshold: number;
  readonly isLoading: boolean;
}

/** What is about to run out, so the shortage is seen before an order fails. */
export function LowStockSummary({ rows, threshold, isLoading }: LowStockSummaryProps) {
  return (
    <Card
      size="small"
      title="Низькі залишки"
      extra={<Link href="/warehouse/stock">Детальніше</Link>}
      styles={{ body: { padding: 0 } }}
    >
      <SimpleTable<StockHealthRow>
        columns={COLUMNS}
        rows={rows}
        isLoading={isLoading}
        rowKey="productId"
        emptyText={`Позицій із залишком до ${threshold} немає`}
      />
    </Card>
  );
}
