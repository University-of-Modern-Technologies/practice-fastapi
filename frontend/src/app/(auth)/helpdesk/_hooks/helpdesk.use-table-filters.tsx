'use client';

import { Button, Checkbox, Select, Space } from 'antd';
import { RotateCcw } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PermissionScope } from '@/shared/api';
import { DateRangeFilter, TextFilter } from '@/components';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { useAuthStore } from '@/shared/stores';
import { type TicketFilter } from '../helpdesk.types';
import {
  TICKET_CHANNEL,
  TICKET_CHANNELS,
  TICKET_PRIORITIES,
  TICKET_PRIORITY,
  TICKET_STATUS,
  TICKET_STATUSES,
} from '@/shared/constants';

interface UseTicketTableFiltersOptions {
  readonly params: ListParams<TicketFilter>;
  readonly onChange: (patch: ListParamsPatch<TicketFilter>) => void;
  readonly onReset: () => void;
  /** The caller's scope on `helpdesk:read`; `OWN` has nothing to narrow by owner. */
  readonly scope: PermissionScope | null;
}

const STATUS_OPTIONS = TICKET_STATUSES.map((status) => ({
  value: status,
  label: TICKET_STATUS[status].label,
}));

const PRIORITY_OPTIONS = TICKET_PRIORITIES.map((priority) => ({
  value: priority,
  label: TICKET_PRIORITY[priority].label,
}));

const CHANNEL_OPTIONS = TICKET_CHANNELS.map((channel) => ({
  value: channel,
  label: TICKET_CHANNEL[channel].label,
}));

/** True when the list is narrowed — an empty result then means "not found". */
export const hasActiveTicketFilters = (params: ListParams<TicketFilter>): boolean =>
  signature(params).trim() !== '';

/** Everything the row shows, flattened — also the identity it is remounted by. */
function signature(params: ListParams<TicketFilter>): string {
  return [
    params.search,
    params.status,
    params.channel,
    params.priority,
    params.contactId,
    params.assigneeId,
    params.ownerId,
    params.openedFrom,
    params.openedTo,
  ]
    .map((value) => value ?? '')
    .join(' ');
}

function TicketFilterRow({ params, onChange, onReset, scope }: UseTicketTableFiltersOptions) {
  const currentUserId = useAuthStore((state) => state.user?.id);

  const isMineOnly = Boolean(currentUserId && params.ownerId === currentUserId);
  const hasFilters = hasActiveTicketFilters(params);

  return (
    <Space wrap size="small">
      <TextFilter
        value={params.search}
        onCommit={(value) => onChange({ search: value })}
        placeholder="Номер або тема"
        width={240}
      />

      <Select
        allowClear
        placeholder="Стан"
        style={{ width: 180 }}
        options={STATUS_OPTIONS}
        value={params.status ?? null}
        onChange={(value: string | null) => onChange({ status: value ?? undefined })}
      />

      <Select
        allowClear
        placeholder="Пріоритет"
        style={{ width: 160 }}
        options={PRIORITY_OPTIONS}
        value={params.priority ?? null}
        onChange={(value: string | null) => onChange({ priority: value ?? undefined })}
      />

      <Select
        allowClear
        placeholder="Канал"
        style={{ width: 150 }}
        options={CHANNEL_OPTIONS}
        value={params.channel ?? null}
        onChange={(value: string | null) => onChange({ channel: value ?? undefined })}
      />

      <DateRangeFilter
        from={params.openedFrom}
        to={params.openedTo}
        onCommit={({ from, to }) => onChange({ openedFrom: from, openedTo: to })}
      />

      {/*
        With scope `OWN` the server already returns nothing but this user's
        tickets, so the control would either repeat what is in force or promise
        a widening it cannot deliver. It is left out instead of being disabled:
        a filter greyed out invites a search for how to enable it.
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
 * The filter row of the ticket list. The query string is the single source of
 * truth: the row is remounted whenever it changes, so a reset, the back button
 * or a shared link all leave the inputs showing what the list is actually
 * filtered by. `contactId` and `assigneeId` have no controls — they arrive from
 * another card as a link and are preserved rather than edited here.
 */
export const useTicketTableFilters = (options: UseTicketTableFiltersOptions): ReactNode => (
  <TicketFilterRow key={signature(options.params)} {...options} />
);
