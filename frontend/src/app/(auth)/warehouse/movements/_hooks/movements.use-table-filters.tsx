'use client';

import { Button, DatePicker, Input, Select } from 'antd';
import type { Dayjs } from 'dayjs';
import type { ReactNode } from 'react';
import { renderSelectNotice } from '@/components';
import { DateTime } from '@/lib/date-time';
import { STOCK_MOVEMENT_TYPE, STOCK_MOVEMENT_TYPES } from '@/shared/constants';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { useWarehouseOptions } from '../../warehouse.queries';

export type MovementFilter =
  | 'warehouseId'
  | 'productId'
  | 'type'
  | 'referenceType'
  | 'referenceId'
  | 'createdFrom'
  | 'createdTo';

interface Options {
  readonly params: ListParams<MovementFilter>;
  readonly setParams: (patch: ListParamsPatch<MovementFilter>) => void;
}

const TYPE_OPTIONS = STOCK_MOVEMENT_TYPES.map((type) => ({
  value: type,
  label: STOCK_MOVEMENT_TYPE[type].label,
}));

export const useMovementFilters = ({ params, setParams }: Options): ReactNode => {
  const { options, isLoading, notice } = useWarehouseOptions();

  const range: [Dayjs | null, Dayjs | null] = [
    DateTime.toPicker(params.createdFrom),
    DateTime.toPicker(params.createdTo),
  ];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        loading={isLoading}
        placeholder="Склад"
        style={{ minWidth: 220 }}
        value={params.warehouseId ?? undefined}
        options={options as { value: string; label: string }[]}
        popupRender={(menu) => renderSelectNotice(menu, notice)}
        onChange={(value: string | undefined) => setParams({ warehouseId: value })}
      />

      <Select
        allowClear
        placeholder="Тип руху"
        style={{ minWidth: 180 }}
        value={params.type ?? undefined}
        options={TYPE_OPTIONS}
        onChange={(value: string | undefined) => setParams({ type: value })}
      />

      <Input
        allowClear
        placeholder="Товар (ідентифікатор)"
        style={{ maxWidth: 280 }}
        defaultValue={params.productId ?? ''}
        onPressEnter={(event) => setParams({ productId: event.currentTarget.value })}
        onChange={(event) => {
          if (event.target.value === '') setParams({ productId: undefined });
        }}
      />

      <Input
        allowClear
        placeholder="Тип підстави"
        style={{ maxWidth: 160 }}
        defaultValue={params.referenceType ?? ''}
        onPressEnter={(event) => setParams({ referenceType: event.currentTarget.value })}
        onChange={(event) => {
          if (event.target.value === '') setParams({ referenceType: undefined });
        }}
      />

      <Input
        allowClear
        placeholder="Підстава (ідентифікатор)"
        style={{ maxWidth: 280 }}
        defaultValue={params.referenceId ?? ''}
        onPressEnter={(event) => setParams({ referenceId: event.currentTarget.value })}
        onChange={(event) => {
          if (event.target.value === '') setParams({ referenceId: undefined });
        }}
      />

      <DatePicker.RangePicker
        showTime
        allowEmpty={[true, true]}
        value={range}
        // The API compares instants, so both ends travel as ISO 8601.
        onChange={(value) =>
          setParams({
            createdFrom: DateTime.toWireDateTime(value?.[0]),
            createdTo: DateTime.toWireDateTime(value?.[1]),
          })
        }
      />

      <Button
        type="link"
        onClick={() =>
          setParams({
            warehouseId: undefined,
            productId: undefined,
            type: undefined,
            referenceType: undefined,
            referenceId: undefined,
            createdFrom: undefined,
            createdTo: undefined,
          })
        }
      >
        Скинути
      </Button>
    </div>
  );
};
