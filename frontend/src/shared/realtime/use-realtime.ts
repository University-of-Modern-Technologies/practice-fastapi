'use client';

import { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from 'react';
import type { RealtimeClient } from './realtime.client';
import type { RealtimeTopic } from './realtime.topics';
import type { RealtimeStatus } from './realtime.types';

/**
 * React surface of the channel. The client itself knows nothing about React;
 * this file is the only place the two meet, which is why the context lives here
 * rather than in the provider.
 */
export const RealtimeContext = createContext<RealtimeClient | null>(null);

export const useRealtimeClient = (): RealtimeClient | null => useContext(RealtimeContext);

/**
 * Holds a subscription for the lifetime of the component. Passing `null` — or
 * rendering with the channel disabled — is a no-op, so a page can ask for a
 * topic unconditionally.
 */
export const useRealtimeTopic = (topic: RealtimeTopic | null | undefined): void => {
  const client = useRealtimeClient();

  useEffect(() => {
    if (!client?.enabled || !topic) return;
    return client.subscribe(topic);
  }, [client, topic]);
};

/** Same, for a page that wants several topics at once. */
export const useRealtimeTopics = (topics: readonly RealtimeTopic[]): void => {
  const client = useRealtimeClient();
  // Joined so a fresh array of the same topics does not resubscribe on every
  // render; the list is short and the values are plain strings.
  const marker = topics.join('|');

  useEffect(() => {
    if (!client?.enabled || marker === '') return;
    const releases = marker.split('|').map((topic) => client.subscribe(topic as RealtimeTopic));
    return () => releases.forEach((release) => release());
  }, [client, marker]);
};

/** The socket is not React state; a store subscription is the honest reading. */
const serverStatus = (): RealtimeStatus => 'disabled';

/** Connection state, for a status indicator in the shell. */
export const useRealtimeStatus = (): RealtimeStatus => {
  const client = useRealtimeClient();

  const subscribe = useCallback(
    (notify: () => void) => client?.onStatus(notify) ?? (() => {}),
    [client],
  );
  const snapshot = useCallback((): RealtimeStatus => client?.getStatus() ?? 'disabled', [client]);

  return useSyncExternalStore(subscribe, snapshot, serverStatus);
};
