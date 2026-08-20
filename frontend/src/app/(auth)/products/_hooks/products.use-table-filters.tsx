'use client';

import { Button, Input, Select, Space } from 'antd';
import { RotateCcw } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Money } from '@/lib/money';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import type { ProductFilter } from '../products.types';
import { priceBoundSchema } from '../products.validation';

interface UseProductTableFiltersOptions {
  readonly params: ListParams<ProductFilter>;
  readonly onChange: (patch: ListParamsPatch<ProductFilter>) => void;
  readonly onReset: () => void;
}

const ACTIVE_OPTIONS = [
  { value: 'true', label: 'Активні' },
  { value: 'false', label: 'Вимкнені' },
];

/**
 * A price bound reaches the query string in the exact shape the API accepts, so
 * a comma typed here never travels as one and a shared link keeps meaning the
 * same amount.
 */
const toBound = (value: string): string | undefined => {
  const trimmed = value.trim();
  if (trimmed === '' || !priceBoundSchema.safeParse(trimmed).success) return undefined;
  return Money.fromInput(trimmed).toWire();
};

/** Everything the row shows, flattened — also the identity it is remounted by. */
const signature = (params: ListParams<ProductFilter>): string =>
  [params.search, params.category, params.isActive, params.minPrice, params.maxPrice]
    .map((value) => value ?? '')
    .join('\u0000');

function ProductFilterRow({ params, onChange, onReset }: UseProductTableFiltersOptions) {
  const [minPrice, setMinPrice] = useState(params.minPrice ?? '');
  const [maxPrice, setMaxPrice] = useState(params.maxPrice ?? '');

  const commitText =
    (key: 'search' | 'category') => (event: { currentTarget: { value: string } }) => {
      const value = event.currentTarget.value.trim();
      if ((params[key] ?? '') === value) return;
      onChange({ [key]: value === '' ? undefined : value } as ListParamsPatch<ProductFilter>);
    };

  const commitBound = (key: 'minPrice' | 'maxPrice', raw: string) => () => {
    const value = toBound(raw);
    // An unparsable amount stays on screen with its error rather than silently
    // dropping out of the filter.
    if (raw.trim() !== '' && value === undefined) return;
    if ((params[key] ?? undefined) === value) return;
    onChange({ [key]: value } as ListParamsPatch<ProductFilter>);
  };

  const boundStatus = (raw: string) =>
    raw.trim() !== '' && toBound(raw) === undefined ? 'error' : '';

  // Committing on blur keeps a keystroke from becoming a request and a history
  // entry; Enter just leaves the field, which commits through the same path.
  const commitOnEnter = (event: { currentTarget: HTMLInputElement }) => event.currentTarget.blur();

  const hasFilters = signature(params).trim() !== '';

  return (
    <Space wrap size="small">
      <Input
        allowClear
        placeholder="Назва або артикул"
        style={{ width: 240 }}
        defaultValue={params.search ?? ''}
        onPressEnter={commitOnEnter}
        onBlur={commitText('search')}
      />

      <Input
        allowClear
        placeholder="Категорія"
        style={{ width: 180 }}
        defaultValue={params.category ?? ''}
        onPressEnter={commitOnEnter}
        onBlur={commitText('category')}
      />

      <Select
        allowClear
        placeholder="Стан"
        style={{ width: 150 }}
        options={ACTIVE_OPTIONS}
        value={params.isActive ?? null}
        onChange={(value: string | null) => onChange({ isActive: value ?? undefined })}
      />

      <Input
        placeholder="Ціна від"
        style={{ width: 130 }}
        inputMode="decimal"
        value={minPrice}
        status={boundStatus(minPrice)}
        onChange={(event) => setMinPrice(event.target.value)}
        onPressEnter={commitOnEnter}
        onBlur={commitBound('minPrice', minPrice)}
      />

      <Input
        placeholder="Ціна до"
        style={{ width: 130 }}
        inputMode="decimal"
        value={maxPrice}
        status={boundStatus(maxPrice)}
        onChange={(event) => setMaxPrice(event.target.value)}
        onPressEnter={commitOnEnter}
        onBlur={commitBound('maxPrice', maxPrice)}
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
 * The filter row of the products list. The query string is the single source of
 * truth: the row is remounted whenever it changes, so a reset, the back button
 * or a shared link all leave the inputs showing what the list is actually
 * filtered by.
 */
export const useProductTableFilters = (options: UseProductTableFiltersOptions): ReactNode => (
  <ProductFilterRow key={signature(options.params)} {...options} />
);
