'use client';

import { Button, Typography } from 'antd';
import Link from 'next/link';
import { useMemo } from 'react';
import { DataTable, DateValue, MoneyValue, type DataTableColumns } from '@/components';
import type { Page } from '@/shared/api';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import type { BankStatement, StatementFilter } from '../finance.types';

interface StatementsTableProps {
  readonly page: Page<BankStatement> | undefined;
  readonly isLoading: boolean;
  readonly params: ListParams<StatementFilter>;
  readonly onParamsChange: (patch: ListParamsPatch<StatementFilter>) => void;
  /** Offered inside the empty state — the import, when the caller may run it. */
  readonly emptyAction?: React.ReactNode;
}

/**
 * The imports themselves.
 *
 * A statement is a container, not a record anyone edits, so it has no card of
 * its own: its one useful action is to open the payments it brought in, and
 * that is a filtered view of the worklist rather than a second screen showing
 * the same rows.
 */
export function StatementsTable({
  page,
  isLoading,
  params,
  onParamsChange,
  emptyAction,
}: StatementsTableProps) {
  const columns: DataTableColumns<BankStatement> = useMemo(
    () => [
      {
        key: 'accountLabel',
        dataIndex: 'accountLabel',
        title: 'Рахунок',
        width: 200,
      },
      {
        key: 'period',
        dataIndex: 'periodStart',
        title: 'Період',
        width: 220,
        render: (_start: string, statement: BankStatement) => (
          <span>
            <DateValue value={statement.periodStart} /> — <DateValue value={statement.periodEnd} />
          </span>
        ),
      },
      {
        key: 'openingBalance',
        dataIndex: 'openingBalance',
        title: 'На початок',
        width: 150,
        align: 'right',
        render: (_value: string, statement: BankStatement) => (
          <MoneyValue value={statement.openingBalance} currency={statement.currency} />
        ),
      },
      {
        key: 'closingBalance',
        dataIndex: 'closingBalance',
        title: 'На кінець',
        width: 150,
        align: 'right',
        render: (_value: string, statement: BankStatement) => (
          <MoneyValue value={statement.closingBalance} currency={statement.currency} showCurrency />
        ),
      },
      {
        key: 'importedAt',
        dataIndex: 'importedAt',
        title: 'Імпортовано',
        width: 160,
        render: (importedAt: string) => <DateValue value={importedAt} withTime />,
      },
      {
        key: 'actions',
        dataIndex: 'id',
        title: '',
        width: 150,
        render: (_id: string, statement: BankStatement) => (
          <Link href={`/finance/transactions?statementId=${statement.id}`}>
            <Button size="small">Платежі</Button>
          </Link>
        ),
      },
    ],
    [],
  );

  return (
    <>
      <Typography.Title level={5}>Виписки</Typography.Title>
      <DataTable<BankStatement, StatementFilter>
        tableId="finance-statements"
        columns={columns}
        page={page}
        isLoading={isLoading}
        params={params}
        onParamsChange={onParamsChange}
        emptyText="Виписок ще немає — імпортуйте першу"
        {...(emptyAction ? { emptyAction } : {})}
      />
    </>
  );
}
