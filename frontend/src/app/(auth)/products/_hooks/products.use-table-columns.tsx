'use client';

import { Tag } from 'antd';
import { useMemo } from 'react';
import {
  CopyableValue,
  DateValue,
  MoneyValue,
  ShowMoreText,
  type DataTableColumns,
} from '@/components';
import type { Product } from '../products.types';

/**
 * Column keys are the API's own sort fields: `DataTable` hands the key it was
 * clicked on straight to `sortBy`, so a mismatch here would silently stop the
 * header arrows from working.
 */
export const useProductTableColumns = (): DataTableColumns<Product> =>
  useMemo(
    () => [
      {
        key: 'sku',
        dataIndex: 'sku',
        title: 'Артикул',
        width: 160,
        sorter: true,
        render: (sku: string) => <CopyableValue value={sku} />,
      },
      {
        key: 'name',
        dataIndex: 'name',
        title: 'Назва',
        width: 260,
        sorter: true,
      },
      {
        key: 'category',
        dataIndex: 'category',
        title: 'Категорія',
        width: 160,
        sorter: true,
        render: (category: string | null) => category ?? '—',
      },
      {
        key: 'unitPrice',
        dataIndex: 'unitPrice',
        title: 'Ціна',
        width: 140,
        align: 'right',
        sorter: true,
        render: (_unitPrice: string, product: Product) => (
          <MoneyValue value={product.unitPrice} currency={product.currency} showCurrency />
        ),
      },
      {
        key: 'isActive',
        dataIndex: 'isActive',
        title: 'Стан',
        width: 120,
        render: (isActive: boolean) => (
          <Tag color={isActive ? 'success' : 'default'}>{isActive ? 'Активний' : 'Вимкнено'}</Tag>
        ),
      },
      {
        key: 'description',
        dataIndex: 'description',
        title: 'Опис',
        width: 280,
        render: (description: string | null) => <ShowMoreText text={description} limit={60} />,
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
