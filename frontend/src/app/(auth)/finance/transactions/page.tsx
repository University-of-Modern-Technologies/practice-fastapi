'use client';

import { Alert, Button, Space } from 'antd';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { DataTable, ModuleUnavailable, PageHeader, PermissionGate } from '@/components';
import { useListParams, useReportError } from '@/shared/hooks';
import { ReconcileButton } from '../_components';
import {
  hasActiveTransactionFilters,
  useTransactionTableColumns,
  useTransactionTableFilters,
} from '../_hooks';
import { useTransactions } from '../finance.queries';
import { isModuleUnavailable, toTransactionListQuery } from '../finance.service';
import {
  TRANSACTION_FILTERS,
  type BankTransaction,
  type TransactionFilter,
} from '../finance.types';

const LIST_DEFAULTS = { sortBy: 'bookedAt', sortOrder: 'desc' } as const;

/**
 * Says what the section is before the first row is read.
 *
 * Without it, a table where most rows say «Не зведено» reads as a list of
 * failures, and the first instinct is to fix them. The notice is permanent and
 * not dismissible on purpose: it is not news about today's data, it is what
 * this table means on every day it is opened.
 */
function ReconciliationNotice() {
  return (
    <Alert
      type="info"
      showIcon
      className="mb-4"
      message="Розбіжність між випискою й замовленнями — робочий стан"
      description="Виписка банку й книга замовлень ведуться незалежно, тож збігаються не всі платежі. «Не зведено» означає, що пари поки немає, а не що щось зламалося. Уваги потребують лише платежі у стані «Потрібен вибір»: там кандидатів кілька, і обрати має людина."
    />
  );
}

function TransactionsList() {
  const router = useRouter();
  const reportError = useReportError();

  const { params, setParams, resetParams } = useListParams<TransactionFilter>({
    filters: TRANSACTION_FILTERS,
    defaults: LIST_DEFAULTS,
  });

  const { data, isLoading, isFetching, isError, error } = useTransactions(
    toTransactionListQuery(params),
  );

  const unavailable = isModuleUnavailable(error);

  useEffect(() => {
    if (isError && !unavailable) reportError(error);
  }, [isError, unavailable, error, reportError]);

  const columns = useTransactionTableColumns();
  const filters = useTransactionTableFilters({
    params,
    onChange: setParams,
    onReset: resetParams,
  });

  const reconcileButton = (
    <PermissionGate resource="finance" action="write" fallback={null}>
      <ReconcileButton onReconciled={() => undefined} />
    </PermissionGate>
  );

  const header = (
    <PageHeader
      title="Платежі"
      description="Рядки банківських виписок і те, до яких замовлень вони належать"
      actions={
        unavailable ? null : (
          <Space wrap>
            <Link href="/finance">
              <Button>До виписок</Button>
            </Link>
            {reconcileButton}
          </Space>
        )
      }
    />
  );

  if (unavailable) {
    return (
      <>
        {header}
        <ModuleUnavailable missing="виписки й зведення платежів" requirement="фінанси потрібні" />
      </>
    );
  }

  const isFiltered = hasActiveTransactionFilters(params);

  return (
    <>
      {header}

      <ReconciliationNotice />

      <DataTable<BankTransaction, TransactionFilter>
        tableId="finance-transactions"
        columns={columns}
        page={data}
        isLoading={isLoading || isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={(row) => router.push(`/finance/transactions/${row.id}`)}
        filters={filters}
        emptyText={
          isFiltered
            ? 'За цим запитом платежів не знайдено'
            : 'Платежів ще немає — імпортуйте виписку'
        }
      />
    </>
  );
}

export default function FinanceTransactionsPage() {
  return (
    <PermissionGate resource="finance" action="read">
      <TransactionsList />
    </PermissionGate>
  );
}
