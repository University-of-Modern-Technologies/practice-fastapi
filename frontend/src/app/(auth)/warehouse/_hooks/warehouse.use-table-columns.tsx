'use client';

import { Tag } from 'antd';
import Link from 'next/link';
import { useMemo } from 'react';
import { CopyableValue, DateValue, type DataTableColumns } from '@/components';
import type { Warehouse } from '../warehouse.types';

export const useWarehouseColumns = (): DataTableColumns<Warehouse> =>
  useMemo(
    () => [
      {
        key: 'code',
        title: 'Код',
        dataIndex: 'code',
        width: 140,
        render: (code: string) => <CopyableValue value={code} />,
      },
      {
        key: 'name',
        title: 'Назва',
        dataIndex: 'name',
      },
      {
        key: 'isActive',
        title: 'Стан',
        dataIndex: 'isActive',
        width: 140,
        render: (isActive: boolean) => (
          <Tag color={isActive ? 'success' : 'default'}>{isActive ? 'Активний' : 'Вимкнений'}</Tag>
        ),
      },
      {
        key: 'createdAt',
        title: 'Створено',
        dataIndex: 'createdAt',
        width: 160,
        render: (value: string) => <DateValue value={value} />,
      },
      {
        key: 'actions',
        title: '',
        width: 180,
        render: (_value: unknown, row: Warehouse) => (
          <span className="flex gap-3" onClick={(event) => event.stopPropagation()}>
            <Link href={`/warehouse/${row.id}`}>Картка</Link>
            <Link href={`/warehouse/stock?warehouseId=${row.id}`}>Залишки</Link>
          </span>
        ),
      },
    ],
    [],
  );
