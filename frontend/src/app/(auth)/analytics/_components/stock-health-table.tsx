'use client';

import { InputNumber, Segmented, Space, Tag, Typography } from 'antd';
import { SimpleTable, type DataTableColumns } from '@/components';
import { formatCount } from '@/lib/number';
import type { StockHealthRow, StockHealthReport } from '../analytics.types';
import { LIMIT_CHOICES, MAX_STOCK_THRESHOLD } from '../analytics.validation';
import { ExportButton, ReportCard } from './report-card';

const EMPTY_TEXT = 'Товарів із запасом нижче порога немає';

const numeric = (value: number) => <span className="numeric">{formatCount(value)}</span>;

/**
 * The same product may be low in two warehouses, so the product id alone does
 * not identify a row. `SimpleTable` keys by a field name, hence the composite
 * one added here.
 */
interface StockHealthTableRow extends StockHealthRow {
  readonly rowId: string;
}

const columns: DataTableColumns<StockHealthTableRow> = [
  {
    title: 'SKU',
    dataIndex: 'sku',
    render: (value: string) => <span className="numeric">{value}</span>,
  },
  { title: 'Товар', dataIndex: 'name' },
  { title: 'Склад', dataIndex: 'warehouseCode' },
  { title: 'На складі', dataIndex: 'quantityOnHand', align: 'right', render: numeric },
  { title: 'Зарезервовано', dataIndex: 'quantityReserved', align: 'right', render: numeric },
  {
    title: 'Доступно',
    dataIndex: 'quantityAvailable',
    align: 'right',
    // The column the report exists for: a zero here means the next order fails.
    render: (value: number) => (
      <Tag color={value <= 0 ? 'error' : 'warning'} className="numeric">
        {formatCount(value)}
      </Tag>
    ),
  },
];

interface StockHealthTableProps {
  readonly report: StockHealthReport | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly threshold: number;
  readonly limit: number;
  readonly onThresholdChange: (threshold: number) => void;
  readonly onLimitChange: (limit: number) => void;
  readonly onExport: () => void;
  readonly isExporting: boolean;
}

/** Looks at the present stock, so the page-wide period does not apply to it. */
export function StockHealthTable({
  report,
  isLoading,
  isError,
  threshold,
  limit,
  onThresholdChange,
  onLimitChange,
  onExport,
  isExporting,
}: StockHealthTableProps) {
  const rows: readonly StockHealthTableRow[] = (report?.items ?? []).map((item) => ({
    ...item,
    rowId: `${item.productId}:${item.warehouseId}`,
  }));

  return (
    <ReportCard
      title="Стан запасів"
      description="Товари, доступний залишок яких не перевищує поріг. Період не враховується."
      extra={
        <Space size={8} wrap>
          <Typography.Text type="secondary">Поріг</Typography.Text>
          <InputNumber
            size="small"
            min={0}
            max={MAX_STOCK_THRESHOLD}
            precision={0}
            style={{ width: 96 }}
            value={threshold}
            onChange={(value) => onThresholdChange(value ?? 0)}
          />
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
      <SimpleTable<StockHealthTableRow>
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        rowKey="rowId"
        emptyText={EMPTY_TEXT}
      />
    </ReportCard>
  );
}
