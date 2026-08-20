'use client';

import { Button, Tooltip, Typography } from 'antd';
import { useMemo } from 'react';
import { CopyableValue, DateValue, PermissionGate, type DataTableColumns } from '@/components';
import type { StockLevel } from '../../warehouse.types';

interface Options {
  /** Opens the operation dialog already pointed at this row. */
  readonly onOperate: (row: StockLevel) => void;
  /** Code and name of a warehouse, so the table shows more than a raw id. */
  readonly warehouseLabels: Readonly<Record<string, string>>;
}

const quantity = (value: number) => <span className="numeric">{value}</span>;

export const useStockColumns = ({
  onOperate,
  warehouseLabels,
}: Options): DataTableColumns<StockLevel> =>
  useMemo(
    () => [
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
        key: 'quantityOnHand',
        title: 'На руках',
        dataIndex: 'quantityOnHand',
        width: 110,
        align: 'right',
        render: quantity,
      },
      {
        key: 'quantityReserved',
        title: 'У резерві',
        dataIndex: 'quantityReserved',
        width: 110,
        align: 'right',
        render: quantity,
      },
      {
        key: 'quantityAvailable',
        title: 'Доступно',
        dataIndex: 'quantityAvailable',
        width: 120,
        align: 'right',
        // Derived by the API as on-hand minus reserved; nothing writes it back.
        render: (value: number) => (
          <Tooltip title="Обчислюється як «на руках» мінус «у резерві»">
            <Typography.Text
              strong
              className="numeric"
              {...(value <= 0 ? { type: 'danger' as const } : {})}
            >
              {value}
            </Typography.Text>
          </Tooltip>
        ),
      },
      {
        key: 'updatedAt',
        title: 'Оновлено',
        dataIndex: 'updatedAt',
        width: 160,
        render: (value: string) => <DateValue value={value} withTime />,
      },
      {
        key: 'actions',
        title: '',
        width: 120,
        render: (_value: unknown, row: StockLevel) => (
          <PermissionGate resource="warehouse" action="write" fallback={null}>
            <Button size="small" onClick={() => onOperate(row)}>
              Операція
            </Button>
          </PermissionGate>
        ),
      },
    ],
    [onOperate, warehouseLabels],
  );
