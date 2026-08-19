'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { getAccessToken, restoreSession } from '@/shared/api';
import {
  createRealtimeClient,
  invalidationKeysFor,
  RealtimeContext,
  type RealtimeClient,
} from '@/shared/realtime';
import { useAuthStore } from '@/shared/stores';

/** Empty value is a supported deployment: the channel simply stays off. */
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? '';

/**
 * Owns the socket for the whole application. It sits inside `SessionProvider`
 * because the channel is only meaningful once a session exists, and inside
 * `QueryProvider` because everything it does ends in an invalidation.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  // Held in state so a re-render never replaces a live socket.
  const [client] = useState<RealtimeClient>(() =>
    createRealtimeClient({
      url: WS_URL,
      // Read per connection: the access token lives in memory and 15 minutes.
      getToken: getAccessToken,
      renewSession: restoreSession,
      onEvent: (event) => {
        for (const queryKey of invalidationKeysFor(event)) {
          void queryClient.invalidateQueries({ queryKey });
        }
      },
    }),
  );

  useEffect(() => {
    if (!client.enabled) return;

    const sync = (status: string): void => {
      if (status === 'authenticated') {
        client.start();
        // A renewal keeps the same status but issues a new token; the client
        // reconnects only when the one it holds is no longer current.
        client.reauthenticate();
      } else if (status === 'anonymous') {
        client.stop();
      }
    };

    sync(useAuthStore.getState().status);
    // Subscribing to the store rather than to `onSession` on purpose: the HTTP
    // layer keeps room for exactly one session listener and `SessionProvider`
    // already holds it.
    const unsubscribe = useAuthStore.subscribe((state) => sync(state.status));

    return () => {
      unsubscribe();
      client.stop();
    };
  }, [client]);

  return <RealtimeContext.Provider value={client}>{children}</RealtimeContext.Provider>;
}
