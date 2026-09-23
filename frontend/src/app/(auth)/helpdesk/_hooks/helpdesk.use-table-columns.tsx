'use client';

import { useMemo } from 'react';
import { DateValue, ShowMoreText, StatusTag, type DataTableColumns } from '@/components';
import { type Ticket } from '../helpdesk.types';
import { TICKET_CHANNEL, TICKET_PRIORITY, TICKET_STATUS } from '@/shared/constants';

/**
 * Column keys are the API's own sort fields: `DataTable` hands the key it was
 * clicked on straight to `sortBy`, so a mismatch here would silently stop the
 * header arrows from working. `subject` and `channel` carry no sorter because
 * the API does not order by them.
 */
export const useTicketTableColumns = (): DataTableColumns<Ticket> =>
  useMemo(
    () => [
      {
        key: 'number',
        dataIndex: 'number',
        title: 'Номер',
        width: 140,
        render: (number: string) => <span className="numeric">{number}</span>,
      },
      {
        key: 'subject',
        dataIndex: 'subject',
        title: 'Тема',
        width: 280,
        render: (subject: string) => <ShowMoreText text={subject} limit={70} />,
      },
      {
        key: 'status',
        dataIndex: 'status',
        title: 'Стан',
        width: 160,
        sorter: true,
        render: (_status: string, ticket: Ticket) => (
          <StatusTag dictionary={TICKET_STATUS} value={ticket.status} />
        ),
      },
      {
        key: 'priority',
        dataIndex: 'priority',
        title: 'Пріоритет',
        width: 140,
        sorter: true,
        render: (_priority: string, ticket: Ticket) => (
          <StatusTag dictionary={TICKET_PRIORITY} value={ticket.priority} />
        ),
      },
      {
        key: 'channel',
        dataIndex: 'channel',
        title: 'Канал',
        width: 130,
        render: (_channel: string, ticket: Ticket) => (
          <StatusTag dictionary={TICKET_CHANNEL} value={ticket.channel} />
        ),
      },
      {
        key: 'openedAt',
        dataIndex: 'openedAt',
        title: 'Відкрито',
        width: 150,
        sorter: true,
        render: (openedAt: string) => <DateValue value={openedAt} />,
      },
      {
        key: 'updatedAt',
        dataIndex: 'updatedAt',
        title: 'Оновлено',
        width: 150,
        sorter: true,
        render: (updatedAt: string) => <DateValue value={updatedAt} />,
      },
    ],
    [],
  );
