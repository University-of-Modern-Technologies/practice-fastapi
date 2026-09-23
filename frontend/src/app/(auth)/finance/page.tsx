'use client';

import { Alert, Button, Space } from 'antd';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  DateRangeFilter,
  ModuleUnavailable,
  PageHeader,
  PermissionGate,
} from '@/components';
import { useListParams, useReportError } from '@/shared/hooks';
import {
  FinanceSummaryCard,
  ImportStatementButton,
  ReconcileButton,
  StatementsTable,
} from './_components';
import { useSummaryRange } from './_hooks';
import { useFinanceSummary, useStatements } from './finance.queries';
import { isModuleUnavailable, toStatementListQuery } from './finance.service';
import { STATEMENT_FILTERS, type StatementFilter } from './finance.types';

/**
 * The bank is reachable only through the import action. Its being down says
 * nothing about the statements already pulled, so the page stays on screen and
 * this line names what actually failed.
 */
function BankDownNotice({ onClose }: { readonly onClose: () => void }) {
  return (
    <Alert
      type="warning"
      showIcon
      closable
      className="mb-4"
      message="Банк недоступний"
      description="Нову виписку зараз не завантажити. Те, що вже імпортовано, читається як звичайно — спробуйте пізніше."
      onClose={onClose}
    />
  );
}

/**
 * What the reconciliation run actually decided, said where the operator is
 * standing rather than only in a toast that disappears.
 *
 * `unmatched` is reported as an outcome and not as a residue: it is the
 * headline number of this section on most days.
 */
function ReconcileSummaryNotice({
  matched,
  suggested,
  unmatched,
  onClose,
}: {
  readonly matched: number;
  readonly suggested: number;
  readonly unmatched: number;
  readonly onClose: () => void;
}) {
  return (
    <Alert
      type="info"
      showIcon
      closable
      className="mb-4"
      message={`Зведено ${matched}, потребують вибору ${suggested}, без пари ${unmatched}`}
      description={
        suggested > 0 ? (
          <span>
            Платежі, де кандидатів кілька, чекають на рішення людини —{' '}
            <Link href="/finance/transactions?matchStatus=SUGGESTED">відкрити їх</Link>.
          </span>
        ) : (
          'Платежі без пари — це нормальний стан: не кожне надходження стосується замовлення.'
        )
      }
      onClose={onClose}
    />
  );
}

function FinanceOverview() {
  const reportError = useReportError();

  const [isBankDown, setIsBankDown] = useState(false);
  const [lastRun, setLastRun] = useState<{
    matched: number;
    suggested: number;
    unmatched: number;
  } | null>(null);

  const { params, setParams } = useListParams<StatementFilter>({ filters: STATEMENT_FILTERS });

  const statements = useStatements(toStatementListQuery(params));

  // The shared reporting month is independent of imported statements, so the
  // summary request starts with the list instead of waiting for it.
  const range = useSummaryRange();

  // A window the API would reject is never sent: the reason is read under the
  // picker instead of arriving as a 400.
  const summary = useFinanceSummary(range.wire, { enabled: range.issue === null });

  const results = [statements, summary];
  const unavailable = results.some((result) => isModuleUnavailable(result.error));
  const failure = results.find(
    (result) => result.isError && !isModuleUnavailable(result.error),
  )?.error;

  useEffect(() => {
    // A section this build does not serve is explained on the page itself, so
    // it must not also arrive as a failure notification.
    if (failure) reportError(failure);
  }, [failure, reportError]);

  const importButton = (
    <PermissionGate resource="finance" action="write" fallback={null}>
      <ImportStatementButton
        onProviderUnavailable={() => setIsBankDown(true)}
        onImported={() => setIsBankDown(false)}
      />
    </PermissionGate>
  );

  const reconcileButton = (
    <PermissionGate resource="finance" action="write" fallback={null}>
      <ReconcileButton
        onReconciled={(result) =>
          setLastRun({
            matched: result.matched,
            suggested: result.suggested,
            unmatched: result.unmatched,
          })
        }
      />
    </PermissionGate>
  );

  const header = (
    <PageHeader
      title="Фінанси"
      description="Виписки банку й зведення платежів із замовленнями"
      actions={
        unavailable ? null : (
          <Space wrap>
            <Link href="/finance/transactions">
              <Button>Платежі</Button>
            </Link>
            {importButton}
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

  return (
    <>
      {header}

      {isBankDown ? <BankDownNotice onClose={() => setIsBankDown(false)} /> : null}

      {lastRun ? (
        <ReconcileSummaryNotice {...lastRun} onClose={() => setLastRun(null)} />
      ) : null}

      <FinanceSummaryCard
        summary={summary.data}
        isLoading={summary.isPending && range.issue === null}
        isError={summary.isError}
        extra={
          <Space size={8} wrap>
            <DateRangeFilter
              from={range.calendar.from}
              to={range.calendar.to}
              onCommit={({ from, to }) => range.setParams({ from, to })}
            />
            <Button size="small" onClick={range.resetParams}>
              Скинути
            </Button>
          </Space>
        }
      />

      {range.issue ? (
        <Alert type="error" showIcon className="mb-4" message={range.issue} />
      ) : null}

      <StatementsTable
        page={statements.data}
        isLoading={statements.isLoading || statements.isFetching}
        params={params}
        onParamsChange={setParams}
        emptyAction={importButton}
      />
    </>
  );
}

/**
 * The one section a role can be excluded from entirely.
 *
 * Every other module hides rows behind a scope; here `viewer` holds no finance
 * grant at all, so the gate refuses the whole page. That is the point of the
 * arrangement, and it has to look like a refusal — a `viewer` who saw an empty
 * statement list would conclude that no money had ever come in.
 */
export default function FinancePage() {
  return (
    <PermissionGate resource="finance" action="read">
      <FinanceOverview />
    </PermissionGate>
  );
}
