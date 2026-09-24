'use client';

import { Button } from 'antd';
import { Download } from 'lucide-react';
import { useMutationFeedback } from '@/shared/hooks';
import { useImportStatement } from '../finance.queries';
import { isProviderUnavailable } from '../finance.service';
import { FINANCE_ERROR_MESSAGES, type StatementImportResult } from '../finance.types';

interface ImportStatementButtonProps {
  /** Raised so the page can say the bank is down without hiding what is stored. */
  readonly onProviderUnavailable: () => void;
  readonly onImported: (result: StatementImportResult) => void;
}

/**
 * `{ statementId, imported, skipped }` read back as a sentence about what
 * changed. An import that brought nothing new is reported as an outcome, not
 * as a failure — the bank stub serves the same statement every time, so the
 * second press is expected to find everything already there.
 */
const describe = (result: StatementImportResult): string =>
  result.imported > 0
    ? `Імпортовано транзакцій: ${result.imported}, уже відомих: ${result.skipped}`
    : `Нових транзакцій немає — усі ${result.skipped} вже у виписці`;

/**
 * Pulls a statement from the bank.
 *
 * Pressing it twice is safe by construction: the bank's own identifier is the
 * idempotency key, so a repeat adds nothing and comes back as `skipped`. That
 * is why the button is not disabled after a successful run — the honest reason
 * to press it again is that the account has moved since.
 */
export function ImportStatementButton({
  onProviderUnavailable,
  onImported,
}: ImportStatementButtonProps) {
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const load = useImportStatement();

  const run = (): void => {
    load.mutate(undefined, {
      onSuccess: (result) => {
        reportSuccess(describe(result));
        onImported(result);
      },
      onError: (error: unknown) => {
        // A bank that is down is a statement about the bank. What has already
        // been imported keeps reading, so this is said on the page rather than
        // thrown as a failure over an empty screen.
        if (isProviderUnavailable(error)) {
          onProviderUnavailable();
          return;
        }
        reportFailureWith(FINANCE_ERROR_MESSAGES)(error);
      },
    });
  };

  return (
    <Button icon={<Download size={16} />} loading={load.isPending} onClick={run}>
      Імпортувати виписку
    </Button>
  );
}
