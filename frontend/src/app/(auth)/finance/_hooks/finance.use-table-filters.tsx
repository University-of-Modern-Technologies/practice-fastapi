'use client';

import { Button, Input, Select, Space } from 'antd';
import { RotateCcw } from 'lucide-react';
import type { ReactNode } from 'react';
import { DateRangeFilter, TextFilter } from '@/components';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import {
  PAYMENT_MATCH_STATUS,
  PAYMENT_MATCH_STATUSES,
  TRANSACTION_DIRECTION,
  TRANSACTION_DIRECTIONS,
  type TransactionFilter,
} from '../finance.types';

interface UseTransactionTableFiltersOptions {
  readonly params: ListParams<TransactionFilter>;
  readonly onChange: (patch: ListParamsPatch<TransactionFilter>) => void;
  readonly onReset: () => void;
}

const DIRECTION_OPTIONS = TRANSACTION_DIRECTIONS.map((direction) => ({
  value: direction,
  label: TRANSACTION_DIRECTION[direction].label,
}));

const MATCH_STATUS_OPTIONS = PAYMENT_MATCH_STATUSES.map((status) => ({
  value: status,
  label: PAYMENT_MATCH_STATUS[status].label,
}));

/** True when the list is narrowed — an empty result then means "not found". */
export const hasActiveTransactionFilters = (
  params: ListParams<TransactionFilter>,
): boolean => signature(params).trim() !== '';

/** Everything the row shows, flattened — also the identity it is remounted by. */
function signature(params: ListParams<TransactionFilter>): string {
  return [
    params.search,
    params.statementId,
    params.matchStatus,
    params.direction,
    params.bookedFrom,
    params.bookedTo,
    params.minAmount,
    params.maxAmount,
  ]
    .map((value) => value ?? '')
    .join(' ');
}

function TransactionFilterRow({
  params,
  onChange,
  onReset,
}: UseTransactionTableFiltersOptions) {
  const hasFilters = hasActiveTransactionFilters(params);

  return (
    <Space wrap size="small">
      {/*
        The term goes to the reference and the counterparty — the two free-text
        fields a payment carries. Labelling it a search by order would promise
        a lookup that is precisely what this section cannot do: whether a
        payment belongs to an order is the question, not the index.
      */}
      <TextFilter
        value={params.search}
        onCommit={(value) => onChange({ search: value })}
        placeholder="Призначення або контрагент"
        width={240}
      />

      {/*
        The queue an operator actually works is "потрібен вибір", so the states
        are a first-class control rather than something to be found by
        scrolling. Every state is offered, including the two that need nothing
        done to them — hiding those would make the section look like a list of
        problems instead of a ledger.
      */}
      <Select
        allowClear
        placeholder="Стан зведення"
        style={{ width: 190 }}
        options={MATCH_STATUS_OPTIONS}
        value={params.matchStatus ?? null}
        onChange={(value: string | null) => onChange({ matchStatus: value ?? undefined })}
      />

      <Select
        allowClear
        placeholder="Напрямок"
        style={{ width: 160 }}
        options={DIRECTION_OPTIONS}
        value={params.direction ?? null}
        onChange={(value: string | null) => onChange({ direction: value ?? undefined })}
      />

      <DateRangeFilter
        from={params.bookedFrom}
        to={params.bookedTo}
        onCommit={({ from, to }) => onChange({ bookedFrom: from, bookedTo: to })}
      />

      {/*
        Amounts, not quantities: they are typed as text and normalised through
        `Money` on the way into the request, so `1,5` narrows the list instead
        of being dropped or, worse, reaching the API as a 400.
      */}
      <Space.Compact>
        <Input
          className="numeric"
          style={{ width: 120 }}
          placeholder="Сума від"
          defaultValue={params.minAmount}
          onBlur={(event) => onChange({ minAmount: event.target.value })}
          onPressEnter={(event) =>
            onChange({ minAmount: (event.target as HTMLInputElement).value })
          }
        />
        <Input
          className="numeric"
          style={{ width: 120 }}
          placeholder="до"
          defaultValue={params.maxAmount}
          onBlur={(event) => onChange({ maxAmount: event.target.value })}
          onPressEnter={(event) =>
            onChange({ maxAmount: (event.target as HTMLInputElement).value })
          }
        />
      </Space.Compact>

      {hasFilters ? (
        <Button icon={<RotateCcw size={14} />} onClick={onReset}>
          Скинути
        </Button>
      ) : null}
    </Space>
  );
}

/**
 * The filter row of the payment worklist. The query string is the single source
 * of truth: the row is remounted whenever it changes, so a reset, the back
 * button or a shared link all leave the inputs showing what the list is
 * actually filtered by. `statementId` has no control — it arrives from the
 * statement table as a link and is preserved rather than edited here.
 */
export const useTransactionTableFilters = (
  options: UseTransactionTableFiltersOptions,
): ReactNode => <TransactionFilterRow key={signature(options.params)} {...options} />;
