'use client';

import { Typography } from 'antd';
import { useMemo } from 'react';
import { DateValue, StatusTag, type DataTableColumns } from '@/components';
import { CallDuration } from '../_components';
import { type Call } from '../calls.types';
import { CALL_DIRECTION, CALL_DISPOSITION } from '@/shared/constants';

/**
 * How far a call has been triaged, said without fetching anything.
 *
 * Resolving the contact and the deal per row would be two requests a line for a
 * column nobody sorts by, so the cell reports what the record itself holds. An
 * untriaged call is the normal state of a fresh one, and it is worded as a
 * stage of work rather than shown as a missing value.
 */
const linkSummary = (call: Call): string => {
  if (call.contactId !== null && call.dealId !== null) return 'Контакт і угода';
  if (call.contactId !== null) return 'Контакт';
  if (call.dealId !== null) return 'Угода';
  return 'Ще не привʼязано';
};

/**
 * Column keys are the API's own sort fields: `DataTable` hands the key it was
 * clicked on straight to `sortBy`, so a mismatch here would silently stop the
 * header arrows from working. The number pair, the disposition and the link
 * state carry no sorter because the API does not order by them.
 */
export const useCallTableColumns = (): DataTableColumns<Call> =>
  useMemo(
    () => [
      {
        key: 'startedAt',
        dataIndex: 'startedAt',
        title: 'Початок',
        width: 160,
        sorter: true,
        render: (startedAt: string) => <DateValue value={startedAt} withTime />,
      },
      {
        key: 'direction',
        dataIndex: 'direction',
        title: 'Напрямок',
        width: 130,
        render: (_direction: string, call: Call) => (
          <StatusTag dictionary={CALL_DIRECTION} value={call.direction} />
        ),
      },
      {
        key: 'numbers',
        dataIndex: 'fromNumber',
        title: 'Номери',
        width: 240,
        render: (_fromNumber: string, call: Call) => (
          <span className="numeric">{`${call.fromNumber} → ${call.toNumber}`}</span>
        ),
      },
      {
        key: 'disposition',
        dataIndex: 'disposition',
        title: 'Результат',
        width: 170,
        render: (_disposition: string, call: Call) => (
          <StatusTag dictionary={CALL_DISPOSITION} value={call.disposition} />
        ),
      },
      {
        key: 'durationSeconds',
        dataIndex: 'durationSeconds',
        title: 'Тривалість',
        width: 130,
        sorter: true,
        render: (_duration: number, call: Call) => <CallDuration seconds={call.durationSeconds} />,
      },
      {
        key: 'links',
        dataIndex: 'contactId',
        title: 'Привʼязка',
        width: 170,
        render: (_contactId: string | null, call: Call) =>
          call.contactId === null && call.dealId === null ? (
            <Typography.Text type="secondary" italic>
              {linkSummary(call)}
            </Typography.Text>
          ) : (
            <span>{linkSummary(call)}</span>
          ),
      },
    ],
    [],
  );
