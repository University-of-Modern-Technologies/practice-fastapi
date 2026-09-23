'use client';

import { Button } from 'antd';
import { RefreshCw } from 'lucide-react';
import { useMutationFeedback } from '@/shared/hooks';
import { useSyncCalls } from '../calls.queries';
import { isProviderUnavailable } from '../calls.service';
import { CALL_SYNC_MESSAGES, type CallSyncResult } from '../calls.types';

interface SyncCallsButtonProps {
  /** Raised so the page can say the provider is down without hiding the journal. */
  readonly onProviderUnavailable: () => void;
  /**
   * Carries the outcome up: what the pull created is not always what the caller
   * will see, and only the page knows the scope it is reading under.
   */
  readonly onSynced: (result: CallSyncResult) => void;
}

/** `{ fetched, created, skipped }` read back as a sentence about what changed. */
const describe = (result: CallSyncResult): string =>
  result.created > 0
    ? `Отримано ${result.fetched}, нових ${result.created}, уже відомих ${result.skipped}`
    : `Нових дзвінків немає — отримано ${result.fetched}, усі вже в журналі`;

/**
 * Pulls a batch of calls from the telephony provider.
 *
 * Pressing it twice is safe by construction: the provider's own identifier is
 * the idempotency key, so a repeat adds nothing and comes back as `skipped`.
 * That is why the button is not disabled after a successful run — the honest
 * reason to press it again is that more calls have happened since.
 */
export function SyncCallsButton({ onProviderUnavailable, onSynced }: SyncCallsButtonProps) {
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const sync = useSyncCalls();

  const run = (): void => {
    sync.mutate(undefined, {
      onSuccess: (result) => {
        reportSuccess(describe(result));
        onSynced(result);
      },
      onError: (error: unknown) => {
        // A provider that is down is a statement about the provider. The
        // journal keeps reading, so this is said on the page rather than
        // thrown as a failure over an empty screen.
        if (isProviderUnavailable(error)) {
          onProviderUnavailable();
          return;
        }
        reportFailureWith(CALL_SYNC_MESSAGES)(error);
      },
    });
  };

  return (
    <Button icon={<RefreshCw size={16} />} loading={sync.isPending} onClick={run}>
      Синхронізувати
    </Button>
  );
}
