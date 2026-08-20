'use client';

import { Descriptions, Table, Typography, type TableProps } from 'antd';
import Link from 'next/link';
import { useMemo } from 'react';
import { CopyableValue, DateValue } from '@/components';
import { EMPTY_VALUE } from '@/lib/date-time';
import {
  auditActionLabel,
  auditEntityLabel,
  auditEntityRoute,
  type AuditJsonValue,
  type AuditRecord,
} from '../audit.types';

interface AuditJsonBlockProps {
  readonly value: AuditJsonValue | null;
}

/** Raw payload, indented. The fallback whenever no better reading exists. */
export function AuditJsonBlock({ value }: AuditJsonBlockProps) {
  if (value === null || value === undefined)
    return <Typography.Text>{EMPTY_VALUE}</Typography.Text>;

  return (
    <pre
      className="numeric m-0 max-h-96 overflow-auto rounded-md p-3 text-xs"
      style={{ background: 'var(--crm-surface-sunken, rgba(127,127,127,0.08))' }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

interface DiffRow {
  readonly id: string;
  readonly field: string;
  readonly before: AuditJsonValue | undefined;
  readonly after: AuditJsonValue | undefined;
}

const asRecord = (
  value: AuditJsonValue | null | undefined,
): Readonly<Record<string, AuditJsonValue>> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Readonly<Record<string, AuditJsonValue>>)
    : null;

const asText = (value: AuditJsonValue | undefined): string => {
  if (value === undefined || value === null || value === '') return EMPTY_VALUE;
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
};

const sameValue = (left: AuditJsonValue | undefined, right: AuditJsonValue | undefined): boolean =>
  JSON.stringify(left ?? null) === JSON.stringify(right ?? null);

interface AuditChangesViewProps {
  readonly changes: AuditJsonValue | null;
}

/**
 * The modules record a change as `{ before, after }`, and a creation as `{ after }`
 * alone. Where that holds, only the fields that actually moved are listed — a
 * dump of two full records leaves the reader diffing them by eye. Any other
 * shape falls back to the raw payload rather than guessing.
 */
export function AuditChangesView({ changes }: AuditChangesViewProps) {
  const root = asRecord(changes);
  const before = asRecord(root?.before);
  const after = asRecord(root?.after);

  const rows = useMemo<readonly DiffRow[]>(() => {
    if (!after) return [];
    const fields = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after)])].sort();

    return fields
      .map((field) => ({
        id: field,
        field,
        before: before?.[field],
        after: after[field],
      }))
      .filter((row) => !sameValue(row.before, row.after));
  }, [before, after]);

  const columns = useMemo<NonNullable<TableProps<DiffRow>['columns']>>(
    () => [
      { key: 'field', title: 'Поле', dataIndex: 'field', width: 200 },
      {
        key: 'before',
        title: 'Було',
        width: 220,
        render: (_value, row) => (
          <Typography.Text type="secondary" delete={row.before !== undefined}>
            {asText(row.before)}
          </Typography.Text>
        ),
      },
      {
        key: 'after',
        title: 'Стало',
        render: (_value, row) => <Typography.Text strong>{asText(row.after)}</Typography.Text>,
      },
    ],
    [],
  );

  if (!after || rows.length === 0) return <AuditJsonBlock value={changes} />;

  return (
    <Table<DiffRow>
      size="small"
      rowKey="id"
      columns={columns}
      dataSource={rows as DiffRow[]}
      pagination={false}
      scroll={{ x: 'max-content' }}
    />
  );
}

interface AuditRecordDetailsProps {
  readonly record: AuditRecord;
}

/** One log entry in full: who, when, and what moved. Read-only throughout. */
export function AuditRecordDetails({ record }: AuditRecordDetailsProps) {
  const route = auditEntityRoute(record.entityType, record.entityId);

  return (
    <div className="flex flex-col gap-4">
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="Коли">
          <DateValue value={record.createdAt} withTime />
        </Descriptions.Item>
        <Descriptions.Item label="Дія">
          {auditActionLabel(record.action)}{' '}
          <Typography.Text type="secondary" className="numeric">
            {record.action}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="Сутність">
          {auditEntityLabel(record.entityType)}
          {route ? (
            <>
              {' · '}
              <Link href={route}>Відкрити запис</Link>
            </>
          ) : null}
        </Descriptions.Item>
        <Descriptions.Item label="ID запису">
          <CopyableValue value={record.entityId} />
        </Descriptions.Item>
        <Descriptions.Item label="Актор">
          {record.actorId ? <CopyableValue value={record.actorId} /> : 'Система'}
        </Descriptions.Item>
        <Descriptions.Item label="IP">
          <span className="numeric">{record.ipAddress ?? EMPTY_VALUE}</span>
        </Descriptions.Item>
        <Descriptions.Item label="ID події">
          <CopyableValue value={record.id} />
        </Descriptions.Item>
      </Descriptions>

      <section>
        <Typography.Title level={5}>Зміни</Typography.Title>
        <AuditChangesView changes={record.changes} />
      </section>

      <section>
        <Typography.Title level={5}>Метадані</Typography.Title>
        <AuditJsonBlock value={record.metadata} />
      </section>
    </div>
  );
}
