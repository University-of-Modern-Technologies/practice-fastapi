'use client';

import { Typography } from 'antd';
import { useMemo } from 'react';
import { DateValue, MoneyValue, StatusTag, type DataTableColumns } from '@/components';
import {
  PAYMENT_MATCH_STATUS,
  TRANSACTION_DIRECTION,
  type BankTransaction,
} from '../finance.types';

/**
 * Columns of the payment worklist.
 *
 * Column keys are the API's own sort fields: `DataTable` hands the key it was
 * clicked on straight to `sortBy`, so a mismatch here would silently stop the
 * header arrows from working. Direction, counterparty and match state carry no
 * sorter, because the API does not order by them.
 */
export const useTransactionTableColumns = (): DataTableColumns<BankTransaction> =>
  useMemo(
    () => [
      {
        key: 'bookedAt',
        dataIndex: 'bookedAt',
        title: 'Проведено',
        width: 150,
        sorter: true,
        render: (bookedAt: string) => <DateValue value={bookedAt} withTime />,
      },
      {
        key: 'direction',
        dataIndex: 'direction',
        title: 'Напрямок',
        width: 140,
        render: (_direction: string, row: BankTransaction) => (
          <StatusTag dictionary={TRANSACTION_DIRECTION} value={row.direction} />
        ),
      },
      {
        key: 'amount',
        dataIndex: 'amount',
        title: 'Сума',
        width: 150,
        sorter: true,
        align: 'right',
        render: (_amount: string, row: BankTransaction) => (
          <MoneyValue value={row.amount} currency={row.currency} showCurrency />
        ),
      },
      {
        key: 'counterparty',
        dataIndex: 'counterpartyName',
        title: 'Контрагент',
        width: 220,
        render: (counterpartyName: string) => <span>{counterpartyName}</span>,
      },
      {
        // The reference is what the rule reads, so it is on screen rather than
        // one click away: an operator scanning the list is reading the same
        // text the matcher read, and can see for themselves why it found
        // nothing.
        key: 'reference',
        dataIndex: 'reference',
        title: 'Призначення платежу',
        render: (reference: string) => (
          <Typography.Text ellipsis={{ tooltip: reference }}>{reference}</Typography.Text>
        ),
      },
      {
        key: 'matchStatus',
        dataIndex: 'matchStatus',
        title: 'Зведення',
        width: 180,
        render: (_status: string, row: BankTransaction) => (
          <StatusTag dictionary={PAYMENT_MATCH_STATUS} value={row.matchStatus} />
        ),
      },
    ],
    [],
  );
