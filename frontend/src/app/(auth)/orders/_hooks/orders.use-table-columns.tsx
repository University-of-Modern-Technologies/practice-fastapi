'use client';

import { useMemo } from 'react';
import {
  CopyableValue,
  DateValue,
  MoneyValue,
  StatusTag,
  type DataTableColumns,
} from '@/components';
import { ORDER_STATUS } from '@/shared/constants';
import type { Order } from '../orders.types';

/**
 * Column keys are the API's own sort fields: `DataTable` hands the key it was
 * clicked on straight to `sortBy`, so a mismatch here would silently stop the
 * header arrows from working.
 */
export const useOrderTableColumns = (): DataTableColumns<Order> =>
  useMemo(
    () => [
      {
        key: 'orderNumber',
        dataIndex: 'orderNumber',
        title: 'Номер',
        width: 180,
        sorter: true,
        render: (orderNumber: string) => <CopyableValue value={orderNumber} />,
      },
      {
        key: 'status',
        dataIndex: 'status',
        title: 'Статус',
        width: 150,
        sorter: true,
        render: (status: string) => <StatusTag dictionary={ORDER_STATUS} value={status} />,
      },
      {
        key: 'items',
        dataIndex: 'items',
        title: 'Позицій',
        width: 100,
        align: 'right',
        render: (items: Order['items']) => <span className="numeric">{items.length}</span>,
      },
      {
        key: 'total',
        dataIndex: 'total',
        title: 'Разом',
        width: 160,
        align: 'right',
        sorter: true,
        render: (_total: string, order: Order) => (
          <MoneyValue value={order.total} currency={order.currency} showCurrency />
        ),
      },
      {
        key: 'placedAt',
        dataIndex: 'placedAt',
        title: 'Розміщено',
        width: 150,
        sorter: true,
        render: (placedAt: string | null) => <DateValue value={placedAt} />,
      },
      {
        key: 'createdAt',
        dataIndex: 'createdAt',
        title: 'Створено',
        width: 150,
        sorter: true,
        render: (createdAt: string) => <DateValue value={createdAt} />,
      },
      {
        key: 'updatedAt',
        dataIndex: 'updatedAt',
        title: 'Оновлено',
        width: 150,
        sorter: true,
        render: (updatedAt: string) => <DateValue value={updatedAt} />,
      },
    ],
    [],
  );
