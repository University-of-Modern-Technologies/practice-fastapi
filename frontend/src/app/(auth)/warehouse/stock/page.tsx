'use client';

import { Button } from 'antd';
import Link from 'next/link';
import { useCallback, useMemo, useState } from 'react';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams } from '@/shared/hooks';
import { StockOperationModal } from '../_components';
import { useStockLevels } from '../stock.queries';
import { useWarehouseOptions } from '../warehouse.queries';
import type { StockLevel } from '../warehouse.types';
import { useStockColumns, useStockFilters, type StockFilter } from './_hooks';

const FILTERS = ['warehouseId', 'productId', 'lowStockThreshold'] as const;

function StockLevels() {
  const { params, setParams } = useListParams<StockFilter>({ filters: FILTERS });
  const [target, setTarget] = useState<StockLevel | null>(null);
  const [isOperationOpen, setOperationOpen] = useState(false);

  const { options } = useWarehouseOptions();
  const warehouseLabels = useMemo(
    () => Object.fromEntries(options.map((option) => [option.value, option.label])),
    [options],
  );

  const threshold = params.lowStockThreshold;
  const { data, isLoading } = useStockLevels({
    page: params.page,
    pageSize: params.pageSize,
    warehouseId: params.warehouseId,
    productId: params.productId,
    lowStockThreshold: threshold === undefined ? undefined : Number(threshold),
  });

  const openOperation = useCallback((row: StockLevel) => {
    setTarget(row);
    setOperationOpen(true);
  }, []);

  const columns = useStockColumns({ onOperate: openOperation, warehouseLabels });
  const filters = useStockFilters({ params, setParams });

  return (
    <>
      <PageHeader
        title="Залишки"
        description="Кількість на руках, у резерві та доступна до відвантаження"
        actions={
          <>
            <Link href="/warehouse/movements">
              <Button>Журнал рухів</Button>
            </Link>
            <PermissionGate resource="warehouse" action="write" fallback={null}>
              <Button
                type="primary"
                onClick={() => {
                  setTarget(null);
                  setOperationOpen(true);
                }}
              >
                Операція
              </Button>
            </PermissionGate>
          </>
        }
      />

      <DataTable<StockLevel, StockFilter>
        tableId="stock-levels"
        columns={columns}
        page={data}
        isLoading={isLoading}
        params={params}
        onParamsChange={setParams}
        emptyText="Залишків за цими умовами немає"
        filters={filters}
      />

      <StockOperationModal
        open={isOperationOpen}
        onClose={() => setOperationOpen(false)}
        defaultWarehouseId={target?.warehouseId ?? params.warehouseId}
        defaultProductId={target?.productId ?? params.productId}
      />
    </>
  );
}

export default function StockPage() {
  // The report is a separate component so that a refused visitor never mounts
  // it: arriving by a direct link must show the notice, not a page firing
  // requests the API answers with 403.
  return (
    <PermissionGate resource="warehouse" action="read">
      <StockLevels />
    </PermissionGate>
  );
}
