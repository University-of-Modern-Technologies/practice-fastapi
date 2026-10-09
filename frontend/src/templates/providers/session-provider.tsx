'use client';

import { useEffect, type ReactNode } from 'react';
import { onSession } from '@/shared/api';
import { applySession, clearSession, resumeSession } from '@/shared/auth';

/**
 * Bridges the HTTP layer and the store. The access token lives in memory, so a
 * reload starts with no session at all; the refresh cookie is what turns a cold
 * page load back into a signed-in one. Losing the session anywhere in the app —
 * including inside a silent background refresh — lands here too.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const unsubscribe = onSession((session) => {
      if (session) applySession(session);
      else clearSession();
    });

    // A cold load with no valid cookie is an ordinary anonymous visit, and an
    // API that cannot answer is a third outcome: either way the status moves
    // off `unknown`, so the guard never waits on a skeleton forever.
    void resumeSession();

    return unsubscribe;
  }, []);

  return <>{children}</>;
}
