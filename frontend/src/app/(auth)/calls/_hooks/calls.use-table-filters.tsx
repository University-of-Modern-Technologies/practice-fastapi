'use client';

import { Button, Checkbox, Select, Space } from 'antd';
import { RotateCcw } from 'lucide-react';
import type { ReactNode } from 'react';
import { DateRangeFilter, TextFilter } from '@/components';
import type { PermissionScope } from '@/shared/api';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { useAuthStore } from '@/shared/stores';
import { type CallFilter } from '../calls.types';
import {
  CALL_DIRECTION,
  CALL_DIRECTIONS,
  CALL_DISPOSITION,
  CALL_DISPOSITIONS,
} from '@/shared/constants';

interface UseCallTableFiltersOptions {
  readonly params: ListParams<CallFilter>;
  readonly onChange: (patch: ListParamsPatch<CallFilter>) => void;
  readonly onReset: () => void;
  /** The caller's scope on `calls:read`; `OWN` has nothing to narrow by owner. */
  readonly scope: PermissionScope | null;
}

const DIRECTION_OPTIONS = CALL_DIRECTIONS.map((direction) => ({
  value: direction,
  label: CALL_DIRECTION[direction].label,
}));

const DISPOSITION_OPTIONS = CALL_DISPOSITIONS.map((disposition) => ({
  value: disposition,
  label: CALL_DISPOSITION[disposition].label,
}));

/**
 * The triage filter. "Not yet attributed" is the queue an operator works
 * through, so it is a first-class choice here rather than something to be
 * inferred by scrolling.
 */
const LINKED_OPTIONS = [
  { value: 'true', label: 'З контактом' },
  { value: 'false', label: 'Без контакту' },
];

/** True when the list is narrowed — an empty result then means "not found". */
export const hasActiveCallFilters = (params: ListParams<CallFilter>): boolean =>
  signature(params).trim() !== '';

/** Everything the row shows, flattened — also the identity it is remounted by. */
function signature(params: ListParams<CallFilter>): string {
  return [
    params.search,
    params.direction,
    params.disposition,
    params.contactId,
    params.dealId,
    params.ownerId,
    params.startedFrom,
    params.startedTo,
    params.hasContact,
  ]
    .map((value) => value ?? '')
    .join(' ');
}

function CallFilterRow({ params, onChange, onReset, scope }: UseCallTableFiltersOptions) {
  const currentUserId = useAuthStore((state) => state.user?.id);

  const isMineOnly = Boolean(currentUserId && params.ownerId === currentUserId);
  const hasFilters = hasActiveCallFilters(params);

  return (
    <Space wrap size="small">
      {/*
        The term is matched against the two numbers and the notes — never
        against the contact, which most calls do not have. Labelling it "search
        by client" would promise a lookup the API does not perform.
      */}
      <TextFilter
        value={params.search}
        onCommit={(value) => onChange({ search: value })}
        placeholder="Номер або нотатки"
        width={220}
      />

      <Select
        allowClear
        placeholder="Напрямок"
        style={{ width: 150 }}
        options={DIRECTION_OPTIONS}
        value={params.direction ?? null}
        onChange={(value: string | null) => onChange({ direction: value ?? undefined })}
      />

      <Select
        allowClear
        placeholder="Результат"
        style={{ width: 180 }}
        options={DISPOSITION_OPTIONS}
        value={params.disposition ?? null}
        onChange={(value: string | null) => onChange({ disposition: value ?? undefined })}
      />

      <Select
        allowClear
        placeholder="Привʼязка"
        style={{ width: 170 }}
        options={LINKED_OPTIONS}
        value={params.hasContact ?? null}
        onChange={(value: string | null) => onChange({ hasContact: value ?? undefined })}
      />

      <DateRangeFilter
        from={params.startedFrom}
        to={params.startedTo}
        onCommit={({ from, to }) => onChange({ startedFrom: from, startedTo: to })}
      />

      {/*
        With scope `OWN` the server already returns nothing but this user's
        calls, so the control would either repeat what is in force or promise a
        widening it cannot deliver. It is left out instead of being disabled: a
        filter greyed out invites a search for how to enable it.
      */}
      {scope === 'ALL' && currentUserId ? (
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
 * The filter row of the call journal. The query string is the single source of
 * truth: the row is remounted whenever it changes, so a reset, the back button
 * or a shared link all leave the inputs showing what the list is actually
 * filtered by. `contactId` and `dealId` have no controls — they arrive from
 * another card as a link and are preserved rather than edited here.
 */
export const useCallTableFilters = (options: UseCallTableFiltersOptions): ReactNode => (
  <CallFilterRow key={signature(options.params)} {...options} />
);
