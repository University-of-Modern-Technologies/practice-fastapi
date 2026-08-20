'use client';

import { Button } from 'antd';
import { Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams } from '@/shared/hooks';
import { useOrderTableColumns, useOrderTableFilters } from './_hooks';
import { useOrders } from './orders.queries';
import { toOrderListQuery } from './orders.service';
import { ORDER_FILTERS, type Order, type OrderFilter } from './orders.types';

export default function OrdersPage() {
  const router = useRouter();
  const { params, setParams, resetParams } = useListParams<OrderFilter>({
    filters: ORDER_FILTERS,
    defaults: { sortBy: 'createdAt', sortOrder: 'desc' },
  });

  const { data, isFetching } = useOrders(toOrderListQuery(params));
  const columns = useOrderTableColumns();
  const filters = useOrderTableFilters({ params, onChange: setParams, onReset: resetParams });

  const createButton = (
    <PermissionGate resource="orders" action="write" fallback={null}>
      <Button type="primary" icon={<Plus size={16} />} onClick={() => router.push('/orders/new')}>
        Створити замовлення
      </Button>
    </PermissionGate>
  );

  return (
    <PermissionGate resource="orders" action="read">
      <PageHeader
        title="Замовлення"
        description="Позиції, суми та статуси замовлень"
        actions={createButton}
      />

      <DataTable<Order, OrderFilter>
        tableId="orders"
        columns={columns}
        page={data}
        isLoading={isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={(order) => router.push(`/orders/${order.id}`)}
        filters={filters}
        emptyText="Замовлень ще немає"
        emptyAction={createButton}
      />
    </PermissionGate>
  );
}
