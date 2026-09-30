'use client';

import { Button } from 'antd';
import { Scale } from 'lucide-react';
import { useMutationFeedback } from '@/shared/hooks';
import { useReconcile } from '../finance.queries';
import { FINANCE_ERROR_MESSAGES, type ReconcileResult } from '../finance.types';

interface ReconcileButtonProps {
  readonly onReconciled: (result: ReconcileResult) => void;
}

/**
 * The four counters read back as a sentence.
 *
 * `unmatched` is named out loud alongside the other two, and deliberately not
 * folded into "не вдалося". A run that examined twelve payments and tied four
 * of them did its job: the remaining eight are money that has no order behind
 * it, which is the ordinary contents of a bank statement.
 */
const describe = (result: ReconcileResult): string =>
  `Перевірено ${result.examined}: зведено ${result.matched}, потребують вибору ${result.suggested}, без пари ${result.unmatched}`;

/**
 * Runs the reconciliation rule over what has been imported.
 *
 * Re-running it is safe and sometimes necessary: a payment that matched
 * nothing yesterday matches an order placed today, so nothing here is disabled
 * after a successful run.
 */
export function ReconcileButton({ onReconciled }: ReconcileButtonProps) {
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const reconcile = useReconcile();

  const run = (): void => {
    reconcile.mutate(undefined, {
      onSuccess: (result) => {
        reportSuccess(describe(result));
        onReconciled(result);
      },
      onError: reportFailureWith(FINANCE_ERROR_MESSAGES),
    });
  };

  return (
    <Button type="primary" icon={<Scale size={16} />} loading={reconcile.isPending} onClick={run}>
      Звести автоматично
    </Button>
  );
}
