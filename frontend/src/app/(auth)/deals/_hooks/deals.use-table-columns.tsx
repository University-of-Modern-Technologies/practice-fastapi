'use client';

import { useMemo } from 'react';
import { DateValue, MoneyValue, StatusTag, type DataTableColumns } from '@/components';
import { DEAL_STAGE } from '@/shared/constants';
import type { Deal } from '../deals.types';

/**
 * Column keys are the API's own sort fields: `DataTable` hands the key it was
 * clicked on straight to `sortBy`, so a mismatch here would silently stop the
 * header arrows from working. `stage` carries no sorter because the API does
 * not order by it — alphabetical stages would mean nothing anyway.
 */
export const useDealTableColumns = (): DataTableColumns<Deal> =>
  useMemo(
    () => [
      {
        key: 'title',
        dataIndex: 'title',
        title: 'Назва',
        width: 280,
        sorter: true,
      },
      {
        key: 'stage',
        dataIndex: 'stage',
        title: 'Стадія',
        width: 150,
        render: (_stage: string, deal: Deal) => (
          <StatusTag dictionary={DEAL_STAGE} value={deal.stage} />
        ),
      },
      {
        key: 'amount',
        dataIndex: 'amount',
        title: 'Сума',
        width: 150,
        align: 'right',
        sorter: true,
        render: (_amount: string, deal: Deal) => (
          <MoneyValue value={deal.amount} currency={deal.currency} showCurrency />
        ),
      },
      {
        key: 'probability',
        dataIndex: 'probability',
        title: 'Ймовірність',
        width: 130,
        align: 'right',
        sorter: true,
        render: (probability: number) => <span className="numeric">{probability} %</span>,
      },
      {
        key: 'expectedCloseDate',
        dataIndex: 'expectedCloseDate',
        title: 'Очікуване закриття',
        width: 170,
        sorter: true,
        render: (expectedCloseDate: string | null) => <DateValue value={expectedCloseDate} />,
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
