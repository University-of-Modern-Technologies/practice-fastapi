'use client';

import { Button, Input, Segmented } from 'antd';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams } from '@/shared/hooks';
import { useWarehouseColumns } from './_hooks';
import { useWarehouses } from './warehouse.queries';
import type { Warehouse } from './warehouse.types';

type Filter = 'search' | 'isActive';

const ACTIVITY_OPTIONS = [
  { value: '', label: 'Усі' },
  { value: 'true', label: 'Активні' },
  { value: 'false', label: 'Вимкнені' },
];

function WarehousesList() {
  const router = useRouter();
  const { params, setParams } = useListParams<Filter>({ filters: ['search', 'isActive'] });
  const columns = useWarehouseColumns();

  const { data, isLoading } = useWarehouses({
    page: params.page,
    pageSize: params.pageSize,
    search: params.search,
    isActive: params.isActive === undefined ? undefined : params.isActive === 'true',
  });

  return (
    <>
      <PageHeader
        title="Склади"
        description="Місця зберігання, за якими ведуться залишки"
        actions={
          <PermissionGate resource="warehouse" action="write" fallback={null}>
            <Link href="/warehouse/new">
              <Button type="primary">Новий склад</Button>
            </Link>
          </PermissionGate>
        }
      />

      <DataTable<Warehouse, Filter>
        tableId="warehouses"
        columns={columns}
        page={data}
        isLoading={isLoading}
        params={params}
        onParamsChange={setParams}
        onRowClick={(row) => router.push(`/warehouse/${row.id}`)}
        emptyText="Складів ще немає"
        filters={
          <div className="flex flex-wrap items-center gap-2">
            <Input
              allowClear
              defaultValue={params.search ?? ''}
              placeholder="Пошук за кодом або назвою"
              style={{ maxWidth: 280 }}
              onPressEnter={(event) => setParams({ search: event.currentTarget.value })}
              onChange={(event) => {
                // Clearing the box must widen the list again straight away.
                if (event.target.value === '') setParams({ search: undefined });
              }}
            />
            <Segmented
              value={params.isActive ?? ''}
              options={ACTIVITY_OPTIONS}
              onChange={(value) => setParams({ isActive: String(value) || undefined })}
            />
            <Link href="/warehouse/stock">Залишки</Link>
            <Link href="/warehouse/movements">Журнал рухів</Link>
          </div>
        }
      />
    </>
  );
}

export default function WarehousesPage() {
  // The list is a separate component so that a refused visitor never mounts it:
  // arriving by a direct link must show the notice, not a page firing requests
  // the API answers with 403.
  return (
    <PermissionGate resource="warehouse" action="read">
      <WarehousesList />
    </PermissionGate>
  );
}
