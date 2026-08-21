'use client';

import { Button } from 'antd';
import Link from 'next/link';
import { useMemo } from 'react';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import type { StockMovementType } from '@/shared/constants';
import { useListParams } from '@/shared/hooks';
import { useStockMovements } from '../movements.queries';
import { useWarehouseOptions } from '../warehouse.queries';
import type { StockMovement } from '../warehouse.types';
import { useMovementColumns, useMovementFilters, type MovementFilter } from './_hooks';

const FILTERS = [
  'warehouseId',
  'productId',
  'type',
  'referenceType',
  'referenceId',
  'createdFrom',
  'createdTo',
] as const;

function StockMovementsLog() {
  const { params, setParams } = useListParams<MovementFilter>({ filters: FILTERS });

  const { options } = useWarehouseOptions();
  const warehouseLabels = useMemo(
    () => Object.fromEntries(options.map((option) => [option.value, option.label])),
    [options],
  );

  const { data, isLoading } = useStockMovements({
    page: params.page,
    pageSize: params.pageSize,
    warehouseId: params.warehouseId,
    productId: params.productId,
    type: params.type as StockMovementType | undefined,
    referenceType: params.referenceType,
    referenceId: params.referenceId,
    createdFrom: params.createdFrom,
    createdTo: params.createdTo,
  });

  const columns = useMovementColumns({ warehouseLabels });
  const filters = useMovementFilters({ params, setParams });

  return (
    <>
      <PageHeader
        title="Журнал рухів"
        description="Кожна операція зі складом лишає тут запис; історія не редагується"
        actions={
          <Link href="/warehouse/stock">
            <Button>Залишки</Button>
          </Link>
        }
      />

      <DataTable<StockMovement, MovementFilter>
        tableId="stock-movements"
        columns={columns}
        page={data}
        isLoading={isLoading}
        params={params}
        onParamsChange={setParams}
        emptyText="Рухів за цими умовами ще немає"
        filters={filters}
      />
    </>
  );
}

export default function StockMovementsPage() {
  // The log is a separate component so that a refused visitor never mounts it:
  // arriving by a direct link must show the notice, not a page firing requests
  // the API answers with 403.
  return (
    <PermissionGate resource="warehouse" action="read">
      <StockMovementsLog />
    </PermissionGate>
  );
}
