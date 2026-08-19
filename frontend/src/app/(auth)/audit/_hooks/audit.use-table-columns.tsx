'use client';

import { Space, Tag, Tooltip, Typography } from 'antd';
import Link from 'next/link';
import type { MouseEvent } from 'react';
import { useMemo } from 'react';
import { CopyableValue, DateValue, ShowMoreText, type DataTableColumns } from '@/components';
import { EMPTY_VALUE } from '@/lib/date-time';
import {
  auditActionLabel,
  auditEntityLabel,
  auditEntityRoute,
  type AuditJsonValue,
  type AuditRecord,
} from '../audit.types';

/** Enough of an identifier to recognise a row; the full value is one copy away. */
const shortId = (id: string): string => id.slice(0, 8);

const compact = (value: AuditJsonValue | null): string | null =>
  value === null || value === undefined ? null : JSON.stringify(value);

/** A link inside a clickable row must navigate, not also open the detail panel. */
const stopRowClick = (event: MouseEvent): void => event.stopPropagation();

interface UseAuditTableColumnsOptions {
  /** The history route already fixes the entity, so its columns add nothing. */
  readonly withEntity?: boolean;
}

export const useAuditTableColumns = ({
  withEntity = true,
}: UseAuditTableColumnsOptions = {}): DataTableColumns<AuditRecord> =>
  useMemo(() => {
    const entityColumns: DataTableColumns<AuditRecord> = [
      {
        key: 'entityType',
        title: 'Сутність',
        width: 150,
        render: (_value, row) => auditEntityLabel(row.entityType),
      },
      {
        key: 'entityId',
        title: 'Запис',
        width: 240,
        render: (_value, row) => {
          if (!row.entityId) return <span>{EMPTY_VALUE}</span>;
          const route = auditEntityRoute(row.entityType, row.entityId);

          return (
            <Space size={8}>
              <Link
                href={`/audit/${encodeURIComponent(row.entityType)}/${row.entityId}`}
                onClick={stopRowClick}
              >
                Історія
              </Link>
              {route ? (
                <Link href={route} onClick={stopRowClick}>
                  Відкрити
                </Link>
              ) : null}
              <CopyableValue value={row.entityId}>{shortId(row.entityId)}</CopyableValue>
            </Space>
          );
        },
      },
    ];

    return [
      {
        key: 'createdAt',
        title: 'Коли',
        width: 160,
        render: (_value, row) => <DateValue value={row.createdAt} withTime />,
      },
      {
        key: 'action',
        title: 'Дія',
        width: 190,
        render: (_value, row) => (
          <Tooltip title={row.action}>
            <Tag>{auditActionLabel(row.action)}</Tag>
          </Tooltip>
        ),
      },
      ...(withEntity ? entityColumns : []),
      {
        key: 'actorId',
        title: 'Актор',
        width: 140,
        render: (_value, row) =>
          row.actorId ? (
            <CopyableValue value={row.actorId}>{shortId(row.actorId)}</CopyableValue>
          ) : (
            <Typography.Text type="secondary">Система</Typography.Text>
          ),
      },
      {
        key: 'changes',
        title: 'Зміни',
        render: (_value, row) => <ShowMoreText text={compact(row.changes)} limit={70} />,
      },
      {
        key: 'metadata',
        title: 'Метадані',
        width: 200,
        render: (_value, row) => <ShowMoreText text={compact(row.metadata)} limit={40} />,
      },
      {
        key: 'ipAddress',
        title: 'IP',
        width: 140,
        render: (_value, row) => <span className="numeric">{row.ipAddress ?? EMPTY_VALUE}</span>,
      },
    ];
  }, [withEntity]);
