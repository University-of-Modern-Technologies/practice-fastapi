'use client';

import { Button, Input, InputNumber, Select } from 'antd';
import type { ReactNode } from 'react';
import { renderSelectNotice } from '@/components';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { useWarehouseOptions } from '../../warehouse.queries';

export type StockFilter = 'warehouseId' | 'productId' | 'lowStockThreshold';

interface Options {
  readonly params: ListParams<StockFilter>;
  readonly setParams: (patch: ListParamsPatch<StockFilter>) => void;
}

/**
 * The filter row of the stock list. It lives beside the table rather than in
 * the page so the page reads as what it shows, not as how it is narrowed down.
 */
export const useStockFilters = ({ params, setParams }: Options): ReactNode => {
  const { options, isLoading, notice } = useWarehouseOptions();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        loading={isLoading}
        placeholder="Склад"
        style={{ minWidth: 240 }}
        value={params.warehouseId ?? undefined}
        options={options as { value: string; label: string }[]}
        popupRender={(menu) => renderSelectNotice(menu, notice)}
        onChange={(value: string | undefined) => setParams({ warehouseId: value })}
      />

      <Input
        allowClear
        placeholder="Товар (ідентифікатор)"
        style={{ maxWidth: 320 }}
        defaultValue={params.productId ?? ''}
        onPressEnter={(event) => setParams({ productId: event.currentTarget.value })}
        onChange={(event) => {
          if (event.target.value === '') setParams({ productId: undefined });
        }}
      />

      <InputNumber
        min={0}
        step={1}
        placeholder="Поріг залишку"
        style={{ width: 160 }}
        value={params.lowStockThreshold === undefined ? null : Number(params.lowStockThreshold)}
        onChange={(value) =>
          setParams({ lowStockThreshold: value === null ? undefined : Number(value) })
        }
      />

      <Button
        type="link"
        onClick={() =>
          setParams({ warehouseId: undefined, productId: undefined, lowStockThreshold: undefined })
        }
      >
        Скинути
      </Button>
    </div>
  );
};
