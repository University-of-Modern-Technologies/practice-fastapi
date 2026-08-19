'use client';

import { useCallback, useState } from 'react';
import { ApiError } from '@/shared/api';

/**
 * A 409 is not "something went wrong" — it means someone else saved the record
 * between the read and the write. Reporting it as a generic failure leaves the
 * user with a stale form and no way forward, so it gets its own state: the page
 * offers a re-read, and the values already typed stay on screen.
 */
export const useVersionConflict = (): {
  hasConflict: boolean;
  /** Returns true when the error was a conflict and is now being shown. */
  handleError: (error: unknown) => boolean;
  clearConflict: () => void;
} => {
  const [hasConflict, setHasConflict] = useState(false);

  const handleError = useCallback((error: unknown): boolean => {
    if (!(error instanceof ApiError) || !error.isConflict) return false;
    setHasConflict(true);
    return true;
  }, []);

  const clearConflict = useCallback(() => setHasConflict(false), []);

  return { hasConflict, handleError, clearConflict };
};
