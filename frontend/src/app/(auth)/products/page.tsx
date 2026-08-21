'use client';

import { Button } from 'antd';
import { Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams } from '@/shared/hooks';
import { useProductTableColumns, useProductTableFilters } from './_hooks';
import { useProducts } from './products.queries';
import { toProductListQuery } from './products.service';
import { PRODUCT_FILTERS, type Product, type ProductFilter } from './products.types';

export default function ProductsPage() {
  const router = useRouter();
  const { params, setParams, resetParams } = useListParams<ProductFilter>({
    filters: PRODUCT_FILTERS,
    defaults: { sortBy: 'createdAt', sortOrder: 'desc' },
  });

  const { data, isFetching } = useProducts(toProductListQuery(params));
  const columns = useProductTableColumns();
  const filters = useProductTableFilters({ params, onChange: setParams, onReset: resetParams });

  return (
    <PermissionGate resource="products" action="read">
      <PageHeader
        title="Товари"
        description="Каталог позицій, доступних для замовлень"
        actions={
          <PermissionGate resource="products" action="write" fallback={null}>
            <Button
              type="primary"
              icon={<Plus size={16} />}
              onClick={() => router.push('/products/new')}
            >
              Додати товар
            </Button>
          </PermissionGate>
        }
      />

      <DataTable<Product, ProductFilter>
        tableId="products"
        columns={columns}
        page={data}
        isLoading={isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={(product) => router.push(`/products/${product.id}`)}
        filters={filters}
        emptyText="Товарів ще немає"
      />
    </PermissionGate>
  );
}
