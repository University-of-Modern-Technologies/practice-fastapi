'use client';

import { Typography } from 'antd';
import { useMemo } from 'react';
import {
  CopyableValue,
  DateValue,
  ShowMoreText,
  StatusTag,
  type DataTableColumns,
} from '@/components';
import { STOCK_MOVEMENT_TYPE } from '@/shared/constants';
import type { StockMovement } from '../../warehouse.types';

interface Options {
  readonly warehouseLabels: Readonly<Record<string, string>>;
}

/**
 * The ledger is append-only, so there is no action column: a movement cannot be
 * edited or removed, only answered with a compensating adjustment.
 */
export const useMovementColumns = ({ warehouseLabels }: Options): DataTableColumns<StockMovement> =>
  useMemo(
    () => [
      {
        key: 'createdAt',
        title: 'Коли',
        dataIndex: 'createdAt',
        width: 160,
        render: (value: string) => <DateValue value={value} withTime />,
      },
      {
        key: 'type',
        title: 'Тип',
        dataIndex: 'type',
        width: 170,
        render: (type: string) => <StatusTag dictionary={STOCK_MOVEMENT_TYPE} value={type} />,
      },
      {
        key: 'warehouseId',
        title: 'Склад',
        dataIndex: 'warehouseId',
        width: 220,
        render: (warehouseId: string) =>
          warehouseLabels[warehouseId] ?? <CopyableValue value={warehouseId} />,
      },
      {
        key: 'productId',
        title: 'Товар',
        dataIndex: 'productId',
        width: 300,
        render: (productId: string) => <CopyableValue value={productId} />,
      },
      {
        key: 'quantity',
        title: 'Кількість',
        dataIndex: 'quantity',
        width: 110,
        align: 'right',
        render: (value: number) => <span className="numeric">{value}</span>,
      },
      {
        key: 'reference',
        title: 'Підстава',
        width: 260,
        render: (_value: unknown, row: StockMovement) =>
          row.referenceType ? (
            <span className="flex flex-col">
              <Typography.Text>{row.referenceType}</Typography.Text>
              <CopyableValue value={row.referenceId} />
            </span>
          ) : (
            <span>—</span>
          ),
      },
      {
        key: 'note',
        title: 'Коментар',
        dataIndex: 'note',
        render: (note: string | null) => <ShowMoreText text={note} />,
      },
    ],
    [warehouseLabels],
  );
