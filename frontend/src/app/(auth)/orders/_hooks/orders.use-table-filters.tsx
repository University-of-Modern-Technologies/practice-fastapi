'use client';

import { Button, Input, Select, Space } from 'antd';
import { RotateCcw } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { TextFilter } from '@/components';
import { Money } from '@/lib/money';
import { ORDER_STATUS, ORDER_STATUSES } from '@/shared/constants';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import type { OrderFilter } from '../orders.types';
import { totalBoundSchema } from '../orders.validation';

interface UseOrderTableFiltersOptions {
  readonly params: ListParams<OrderFilter>;
  readonly onChange: (patch: ListParamsPatch<OrderFilter>) => void;
  readonly onReset: () => void;
}

const STATUS_OPTIONS = ORDER_STATUSES.map((status) => ({
  value: status,
  label: ORDER_STATUS[status].label,
}));

/**
 * A bound reaches the query string in the exact shape the API accepts, so a
 * comma typed here never travels as one and a shared link keeps meaning the
 * same amount.
 */
const toBound = (value: string): string | undefined => {
  const trimmed = value.trim();
  if (trimmed === '' || !totalBoundSchema.safeParse(trimmed).success) return undefined;
  return Money.fromInput(trimmed).toWire();
};

/** Everything the row shows, flattened — also the identity it is remounted by. */
const signature = (params: ListParams<OrderFilter>): string =>
  [
    params.search,
    params.status,
    params.ownerId,
    params.contactId,
    params.dealId,
    params.minTotal,
    params.maxTotal,
  ]
    .map((value) => value ?? '')
    .join(' ');

function OrderFilterRow({ params, onChange, onReset }: UseOrderTableFiltersOptions) {
  const [minTotal, setMinTotal] = useState(params.minTotal ?? '');
  const [maxTotal, setMaxTotal] = useState(params.maxTotal ?? '');

  const commitBound = (key: 'minTotal' | 'maxTotal', raw: string) => () => {
    const value = toBound(raw);
    // An unparsable amount stays on screen with its error rather than silently
    // dropping out of the filter.
    if (raw.trim() !== '' && value === undefined) return;
    if ((params[key] ?? undefined) === value) return;
    onChange({ [key]: value } as ListParamsPatch<OrderFilter>);
  };

  const boundStatus = (raw: string) =>
    raw.trim() !== '' && toBound(raw) === undefined ? 'error' : '';

  // Committing on blur keeps a keystroke from becoming a request and a history
  // entry; Enter just leaves the field, which commits through the same path.
  const commitOnEnter = (event: { currentTarget: HTMLInputElement }) => event.currentTarget.blur();

  const hasFilters = signature(params).trim() !== '';

  return (
    <Space wrap size="small">
      <TextFilter
        value={params.search}
        onCommit={(value) => onChange({ search: value })}
        placeholder="Номер замовлення"
        width={220}
      />

      <Select
        allowClear
        placeholder="Статус"
        style={{ width: 170 }}
        options={STATUS_OPTIONS}
        value={params.status ?? null}
        onChange={(value: string | null) => onChange({ status: value ?? undefined })}
      />

      <TextFilter
        value={params.ownerId}
        onCommit={(value) => onChange({ ownerId: value })}
        placeholder="Відповідальний (ID)"
        width={200}
      />

      <TextFilter
        value={params.contactId}
        onCommit={(value) => onChange({ contactId: value })}
        placeholder="Контакт (ID)"
        width={200}
      />

      <TextFilter
        value={params.dealId}
        onCommit={(value) => onChange({ dealId: value })}
        placeholder="Угода (ID)"
        width={200}
      />

      <Input
        placeholder="Сума від"
        style={{ width: 130 }}
        inputMode="decimal"
        value={minTotal}
        status={boundStatus(minTotal)}
        onChange={(event) => setMinTotal(event.target.value)}
        onPressEnter={commitOnEnter}
        onBlur={commitBound('minTotal', minTotal)}
      />

      <Input
        placeholder="Сума до"
        style={{ width: 130 }}
        inputMode="decimal"
        value={maxTotal}
        status={boundStatus(maxTotal)}
        onChange={(event) => setMaxTotal(event.target.value)}
        onPressEnter={commitOnEnter}
        onBlur={commitBound('maxTotal', maxTotal)}
      />

      {hasFilters ? (
        <Button icon={<RotateCcw size={14} />} onClick={onReset}>
          Скинути
        </Button>
      ) : null}
    </Space>
  );
}

/**
 * The filter row of the orders list. The query string is the single source of
 * truth: the row is remounted whenever it changes, so a reset, the back button
 * or a shared link all leave the inputs showing what the list is actually
 * filtered by.
 */
export const useOrderTableFilters = (options: UseOrderTableFiltersOptions): ReactNode => (
  <OrderFilterRow key={signature(options.params)} {...options} />
);
