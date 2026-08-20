'use client';

import { Button, Checkbox, Input, Space } from 'antd';
import type { ReactNode } from 'react';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { useAuthStore } from '@/shared/stores';
import type { ContactFilter } from '../contacts.types';

interface UseContactsTableFiltersOptions {
  readonly params: ListParams<ContactFilter>;
  readonly setParams: (patch: ListParamsPatch<ContactFilter>) => void;
  readonly resetParams: () => void;
}

/** True when the list is narrowed — an empty result then means "not found". */
export const hasActiveContactFilters = (params: ListParams<ContactFilter>): boolean =>
  Boolean(params.search || params.ownerId);

export const useContactsTableFilters = ({
  params,
  setParams,
  resetParams,
}: UseContactsTableFiltersOptions): { filters: ReactNode } => {
  const currentUserId = useAuthStore((state) => state.user?.id);
  const search = params.search ?? '';

  const isFiltered = hasActiveContactFilters(params);
  const isMineOnly = Boolean(currentUserId && params.ownerId === currentUserId);

  const filters = (
    <Space wrap>
      {/*
        The query string is the source of truth, so the field is remounted with
        it: going back, resetting, or opening a shared link all show the term
        that is actually filtering the rows. Typing itself does not re-request —
        the search runs on Enter or on the button.
      */}
      <Input.Search
        key={search}
        allowClear
        placeholder="Імʼя, прізвище, пошта, компанія"
        style={{ width: 320 }}
        defaultValue={search}
        onChange={(event) => {
          if (event.target.value === '' && search !== '') setParams({ search: undefined });
        }}
        onSearch={(value) => setParams({ search: value.trim() || undefined })}
      />

      {currentUserId ? (
        <Checkbox
          checked={isMineOnly}
          onChange={(event) =>
            setParams({ ownerId: event.target.checked ? currentUserId : undefined })
          }
        >
          Лише мої
        </Checkbox>
      ) : null}

      {isFiltered ? (
        <Button type="link" onClick={resetParams}>
          Скинути
        </Button>
      ) : null}
    </Space>
  );

  return { filters };
};
