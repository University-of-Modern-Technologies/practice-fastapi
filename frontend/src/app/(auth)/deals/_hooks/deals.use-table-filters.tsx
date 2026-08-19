'use client';

import { Button, Checkbox, Input, InputNumber, Select, Space } from 'antd';
import { RotateCcw } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { DateRangeFilter, TextFilter } from '@/components';
import { Money } from '@/lib/money';
import { DEAL_STAGE, DEAL_STAGES } from '@/shared/constants';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { useAuthStore } from '@/shared/stores';
import type { DealFilter } from '../deals.types';
import { amountBoundSchema } from '../deals.validation';

interface UseDealTableFiltersOptions {
  readonly params: ListParams<DealFilter>;
  readonly onChange: (patch: ListParamsPatch<DealFilter>) => void;
  readonly onReset: () => void;
}

const STAGE_OPTIONS = DEAL_STAGES.map((stage) => ({
  value: stage,
  label: DEAL_STAGE[stage].label,
}));

/**
 * An amount bound reaches the query string in the exact shape the API accepts,
 * so a comma typed here never travels as one and a shared link keeps meaning
 * the same amount.
 */
const toBound = (value: string): string | undefined => {
  const trimmed = value.trim();
  if (trimmed === '' || !amountBoundSchema.safeParse(trimmed).success) return undefined;
  return Money.fromInput(trimmed).toWire();
};

/** Everything the row shows, flattened — also the identity it is remounted by. */
const signature = (params: ListParams<DealFilter>): string =>
  [
    params.search,
    params.ownerId,
    params.contactId,
    params.stage,
    params.minAmount,
    params.maxAmount,
    params.minProbability,
    params.maxProbability,
    params.expectedCloseFrom,
    params.expectedCloseTo,
  ]
    .map((value) => value ?? '')
    .join(' ');

function DealFilterRow({ params, onChange, onReset }: UseDealTableFiltersOptions) {
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [minAmount, setMinAmount] = useState(params.minAmount ?? '');
  const [maxAmount, setMaxAmount] = useState(params.maxAmount ?? '');

  const commitBound = (key: 'minAmount' | 'maxAmount', raw: string) => () => {
    const value = toBound(raw);
    // An unparsable amount stays on screen with its error rather than silently
    // dropping out of the filter.
    if (raw.trim() !== '' && value === undefined) return;
    if ((params[key] ?? undefined) === value) return;
    onChange({ [key]: value } as ListParamsPatch<DealFilter>);
  };

  const boundStatus = (raw: string) =>
    raw.trim() !== '' && toBound(raw) === undefined ? 'error' : '';

  // Committing on blur keeps a keystroke from becoming a request and a history
  // entry; Enter just leaves the field, which commits through the same path.
  const commitOnEnter = (event: { currentTarget: HTMLInputElement }) => event.currentTarget.blur();

  const commitPercent =
    (key: 'minProbability' | 'maxProbability') =>
    (value: number | null): void => {
      onChange({ [key]: value ?? undefined } as ListParamsPatch<DealFilter>);
    };

  const isMineOnly = Boolean(currentUserId && params.ownerId === currentUserId);
  const hasFilters = signature(params).trim() !== '';

  return (
    <Space wrap size="small">
      <TextFilter
        value={params.search}
        onCommit={(value) => onChange({ search: value })}
        placeholder="Назва угоди"
        width={240}
      />

      <Select
        allowClear
        placeholder="Стадія"
        style={{ width: 170 }}
        options={STAGE_OPTIONS}
        value={params.stage ?? null}
        onChange={(value: string | null) => onChange({ stage: value ?? undefined })}
      />

      <Input
        placeholder="Сума від"
        style={{ width: 130 }}
        inputMode="decimal"
        value={minAmount}
        status={boundStatus(minAmount)}
        onChange={(event) => setMinAmount(event.target.value)}
        onPressEnter={commitOnEnter}
        onBlur={commitBound('minAmount', minAmount)}
      />

      <Input
        placeholder="Сума до"
        style={{ width: 130 }}
        inputMode="decimal"
        value={maxAmount}
        status={boundStatus(maxAmount)}
        onChange={(event) => setMaxAmount(event.target.value)}
        onPressEnter={commitOnEnter}
        onBlur={commitBound('maxAmount', maxAmount)}
      />

      <InputNumber
        placeholder="Ймовірність від"
        style={{ width: 150 }}
        min={0}
        max={100}
        precision={0}
        value={params.minProbability === undefined ? null : Number(params.minProbability)}
        onChange={commitPercent('minProbability')}
      />

      <InputNumber
        placeholder="Ймовірність до"
        style={{ width: 150 }}
        min={0}
        max={100}
        precision={0}
        value={params.maxProbability === undefined ? null : Number(params.maxProbability)}
        onChange={commitPercent('maxProbability')}
      />

      <DateRangeFilter
        from={params.expectedCloseFrom}
        to={params.expectedCloseTo}
        onCommit={({ from, to }) => onChange({ expectedCloseFrom: from, expectedCloseTo: to })}
      />

      {currentUserId ? (
        <Checkbox
          checked={isMineOnly}
          onChange={(event) =>
            onChange({ ownerId: event.target.checked ? currentUserId : undefined })
          }
        >
          Лише мої
        </Checkbox>
      ) : null}

      {hasFilters ? (
        <Button icon={<RotateCcw size={14} />} onClick={onReset}>
          Скинути
        </Button>
      ) : null}
    </Space>
  );
}

/**
 * The filter row of the deals list. The query string is the single source of
 * truth: the row is remounted whenever it changes, so a reset, the back button
 * or a shared link all leave the inputs showing what the list is actually
 * filtered by. `contactId` has no control — it arrives from a contact card as a
 * link and is preserved rather than edited here.
 */
export const useDealTableFilters = (options: UseDealTableFiltersOptions): ReactNode => (
  <DealFilterRow key={signature(options.params)} {...options} />
);
