'use client';

import { Button, DatePicker, Input, Select, Space, Typography } from 'antd';
import type { Dayjs } from 'dayjs';
import { useState, type ReactNode } from 'react';
import { DateTime } from '@/lib/date-time';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { AUDIT_ENTITY_TYPES, auditEntityLabel } from '../audit.types';

export const AUDIT_FILTERS = [
  'action',
  'entityType',
  'entityId',
  'actorId',
  'createdFrom',
  'createdTo',
] as const;

export type AuditFilter = (typeof AUDIT_FILTERS)[number];

/** The API pages the log 25 rows at a time; the client asks for the same. */
export const AUDIT_PAGE_SIZE = 25;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface FilterInputProps {
  readonly placeholder: string;
  readonly value: string | undefined;
  readonly onCommit: (next: string | undefined) => void;
  readonly width: number;
}

/**
 * Applied on Enter or on leaving the field, not on every keystroke. The caller
 * keys these on the committed value, so a filter cleared elsewhere remounts the
 * input with the new text rather than syncing it through an effect.
 */
function TextFilter({ placeholder, value, onCommit, width }: FilterInputProps) {
  const [text, setText] = useState(value ?? '');

  const commit = () => {
    const trimmed = text.trim();
    onCommit(trimmed === '' ? undefined : trimmed);
  };

  return (
    <Input
      allowClear
      style={{ width }}
      placeholder={placeholder}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        if (event.target.value === '') onCommit(undefined);
      }}
      onBlur={commit}
      onPressEnter={commit}
    />
  );
}

/**
 * The API accepts only a complete identifier here and answers 400 to anything
 * shorter. Holding a half-typed value back turns that rejection into a hint
 * next to the field instead of an error notification.
 */
function UuidFilter({ placeholder, value, onCommit, width }: FilterInputProps) {
  const [text, setText] = useState(value ?? '');
  const [error, setError] = useState<string | null>(null);

  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === '') {
      setError(null);
      onCommit(undefined);
      return;
    }
    if (!UUID_PATTERN.test(trimmed)) {
      setError('Вкажіть повний ідентифікатор');
      return;
    }
    setError(null);
    onCommit(trimmed);
  };

  return (
    <div style={{ width }}>
      <Input
        allowClear
        className="numeric"
        placeholder={placeholder}
        value={text}
        {...(error ? { status: 'error' as const } : {})}
        onChange={(event) => {
          setText(event.target.value);
          setError(null);
          if (event.target.value === '') onCommit(undefined);
        }}
        onBlur={commit}
        onPressEnter={commit}
      />
      {error ? (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          {error}
        </Typography.Text>
      ) : null}
    </div>
  );
}

interface UseAuditTableFiltersOptions {
  readonly params: ListParams<AuditFilter>;
  readonly setParams: (patch: ListParamsPatch<AuditFilter>) => void;
  readonly resetParams: () => void;
  /** The history route fixes the entity, so those two filters are dropped. */
  readonly withEntity?: boolean;
}

export const useAuditTableFilters = ({
  params,
  setParams,
  resetParams,
  withEntity = true,
}: UseAuditTableFiltersOptions): ReactNode => {
  const range: [Dayjs | null, Dayjs | null] = [
    DateTime.toPicker(params.createdFrom),
    DateTime.toPicker(params.createdTo),
  ];

  return (
    <Space wrap align="start">
      <TextFilter
        key={`action:${params.action ?? ''}`}
        placeholder="Дія, напр. deal.updated"
        width={220}
        value={params.action}
        onCommit={(next) => setParams({ action: next })}
      />

      {withEntity ? (
        <>
          <Select
            allowClear
            style={{ width: 200 }}
            placeholder="Тип сутності"
            value={params.entityType ?? null}
            onChange={(next: string | null) => setParams({ entityType: next ?? undefined })}
            options={AUDIT_ENTITY_TYPES.map((type) => ({
              value: type,
              label: auditEntityLabel(type),
            }))}
          />
          <UuidFilter
            key={`entityId:${params.entityId ?? ''}`}
            placeholder="ID сутності"
            width={280}
            value={params.entityId}
            onCommit={(next) => setParams({ entityId: next })}
          />
        </>
      ) : null}

      <UuidFilter
        key={`actorId:${params.actorId ?? ''}`}
        placeholder="ID актора"
        width={280}
        value={params.actorId}
        onCommit={(next) => setParams({ actorId: next })}
      />

      <DatePicker.RangePicker
        showTime
        allowEmpty={[true, true]}
        placeholder={['Від', 'До']}
        value={range}
        onChange={(next) =>
          // The endpoint wants full instants with an offset, not calendar dates.
          setParams({
            createdFrom: DateTime.toWireDateTime(next?.[0]),
            createdTo: DateTime.toWireDateTime(next?.[1]),
          })
        }
      />

      <Button onClick={resetParams}>Очистити</Button>
    </Space>
  );
};
