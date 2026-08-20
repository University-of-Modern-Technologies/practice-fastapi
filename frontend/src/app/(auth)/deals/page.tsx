'use client';

import { Button } from 'antd';
import { Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams } from '@/shared/hooks';
import { useDealTableColumns, useDealTableFilters } from './_hooks';
import { useDeals } from './deals.queries';
import { toDealListQuery } from './deals.service';
import { DEAL_FILTERS, type Deal, type DealFilter } from './deals.types';

export default function DealsPage() {
  const router = useRouter();
  const { params, setParams, resetParams } = useListParams<DealFilter>({
    filters: DEAL_FILTERS,
    defaults: { sortBy: 'createdAt', sortOrder: 'desc' },
  });

  const { data, isFetching } = useDeals(toDealListQuery(params));
  const columns = useDealTableColumns();
  const filters = useDealTableFilters({ params, onChange: setParams, onReset: resetParams });

  const createButton = (
    <PermissionGate resource="deals" action="write" fallback={null}>
      <Button type="primary" icon={<Plus size={16} />} onClick={() => router.push('/deals/new')}>
        Додати угоду
      </Button>
    </PermissionGate>
  );

  return (
    <PermissionGate resource="deals" action="read">
      <PageHeader
        title="Угоди"
        description="Продажі на всіх стадіях — від ліда до закриття"
        actions={createButton}
      />

      <DataTable<Deal, DealFilter>
        tableId="deals"
        columns={columns}
        page={data}
        isLoading={isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={(deal) => router.push(`/deals/${deal.id}`)}
        filters={filters}
        emptyText="Угод ще немає"
        emptyAction={createButton}
      />
    </PermissionGate>
  );
}
