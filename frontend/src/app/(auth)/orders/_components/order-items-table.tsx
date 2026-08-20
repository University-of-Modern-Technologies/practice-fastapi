'use client';

import { Alert, Button, InputNumber, Space } from 'antd';
import { Trash2 } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import { DeleteConfirm, MoneyValue, SimpleTable, type DataTableColumns } from '@/components';
import type { CurrencyCode } from '@/types/domain';
import type { OrderItemView } from '../orders.types';

interface OrderItemsTableProps {
  readonly items: readonly OrderItemView[];
  readonly currency: CurrencyCode;
  /** False once the order has left `DRAFT`: the lines then only get read. */
  readonly isEditable: boolean;
  readonly isPending?: boolean;
  readonly onQuantityChange?: (item: OrderItemView, quantity: number) => void;
  readonly onRemove?: (item: OrderItemView) => void;
  /** Offered inside the empty state — the «add a line» button. */
  readonly emptyAction?: ReactNode;
}

/**
 * The lines of an order. The quantity is edited in place rather than through a
 * dialog: it is the single field of a line the API lets anyone change, and a
 * modal around one number would cost two clicks per correction.
 */
export function OrderItemsTable({
  items,
  currency,
  isEditable,
  isPending = false,
  onQuantityChange,
  onRemove,
  emptyAction,
}: OrderItemsTableProps) {
  const columns = useMemo<DataTableColumns<OrderItemView>>(() => {
    const base: DataTableColumns<OrderItemView> = [
      { key: 'sku', dataIndex: 'sku', title: 'Артикул', width: 150 },
      { key: 'name', dataIndex: 'name', title: 'Товар' },
      {
        key: 'quantity',
        dataIndex: 'quantity',
        title: 'Кількість',
        width: 150,
        align: 'right',
        render: (quantity: number, item: OrderItemView) =>
          isEditable && onQuantityChange ? (
            <InputNumber
              // Remounted when the saved quantity changes, so a rejected write
              // leaves the field showing what the server actually holds.
              key={`${item.id}:${quantity}`}
              min={1}
              max={1_000_000}
              step={1}
              precision={0}
              disabled={isPending}
              defaultValue={quantity}
              style={{ width: '100%' }}
              onPressEnter={(event) => event.currentTarget.blur()}
              onBlur={(event) => {
                const next = Number(event.currentTarget.value.replace(/\s/g, ''));
                if (!Number.isInteger(next) || next < 1 || next === quantity) return;
                onQuantityChange(item, next);
              }}
            />
          ) : (
            <span className="numeric">{quantity}</span>
          ),
      },
      {
        key: 'unitPrice',
        dataIndex: 'unitPrice',
        title: 'Ціна',
        width: 140,
        align: 'right',
        render: (unitPrice: string) => (
          <MoneyValue value={unitPrice} currency={currency} showCurrency />
        ),
      },
      {
        key: 'lineTotal',
        dataIndex: 'lineTotal',
        title: 'Сума',
        width: 150,
        align: 'right',
        render: (lineTotal: string) => (
          <MoneyValue value={lineTotal} currency={currency} showCurrency />
        ),
      },
    ];

    if (!isEditable || !onRemove) return base;

    return [
      ...base,
      {
        key: 'actions',
        title: '',
        width: 70,
        align: 'right',
        render: (_value: unknown, item: OrderItemView) => (
          <DeleteConfirm
            onConfirm={() => onRemove(item)}
            isPending={isPending}
            title="Прибрати позицію?"
            description="Суми замовлення буде перераховано."
            okText="Прибрати"
          >
            <Button size="small" danger type="text" icon={<Trash2 size={14} />} />
          </DeleteConfirm>
        ),
      },
    ];
  }, [currency, isEditable, isPending, onQuantityChange, onRemove]);

  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      {isEditable ? null : (
        <Alert type="info" showIcon message="Замовлення вже підтверджено — позиції не змінюються" />
      )}

      <SimpleTable<OrderItemView>
        columns={columns}
        rows={items}
        isLoading={false}
        rowKey="id"
        emptyText="Позицій ще немає"
        emptyAction={emptyAction}
      />
    </Space>
  );
}
