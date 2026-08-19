'use client';

import { useEffect, type ReactNode } from 'react';
import { onSession, restoreSession } from '@/shared/api';
import { applySession, clearSession } from '@/shared/auth';

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

    void restoreSession().then((token) => {
      // A cold load with no valid cookie is an ordinary anonymous visit, not an
      // error: the status has to move off `unknown` so the guard can act.
      if (!token) clearSession();
    });

    return unsubscribe;
  }, []);

  return <>{children}</>;
}
