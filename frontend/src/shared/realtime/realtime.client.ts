import {
  BEARER_SUBPROTOCOL,
  CLOSE_CODE_NORMAL,
  CLOSE_CODE_POLICY_VIOLATION,
  parseDomainEvent,
  parseOutboundFrame,
  REALTIME_ERROR_CODES,
  type RealtimeDomainEvent,
  type RealtimeStatus,
} from './realtime.types';
import {
  isRealtimeTopic,
  MAX_SUBSCRIPTIONS_PER_CONNECTION,
  type RealtimeTopic,
} from './realtime.topics';

/**
 * Transport-agnostic socket client. Deliberately free of React: the hook and the
 * provider wrap it the same way `*.queries.ts` wraps a `*.service.ts`, which is
 * what makes the reconnect and heartbeat logic testable against a plain fake.
 */

/** Ping period. Shorter than the server's 30 s heartbeat window, on purpose. */
const HEARTBEAT_INTERVAL_MS = 15_000;

/** A `ping` this old without a `pong` means the connection is gone. */
const PONG_TIMEOUT_MS = 10_000;

const INITIAL_RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 30_000;

const SOCKET_OPEN = 1;

/** Structural view of a browser `WebSocket`; a fake satisfies it in tests. */
export interface RealtimeSocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: (() => void) | null;
  onmessage: ((event: { readonly data: unknown }) => void) | null;
  onclose: ((event: { readonly code: number }) => void) | null;
  onerror: (() => void) | null;
}

export type RealtimeSocketFactory = (
  url: string,
  protocols: readonly string[],
) => RealtimeSocketLike;

export interface RealtimeClientOptions {
  /** Empty value disables the channel outright. */
  readonly url: string;
  /** Read at connect time, never cached: the access token lives 15 minutes. */
  readonly getToken: () => string | null;
  /** Single attempt to renew the session after a refused handshake. */
  readonly renewSession: () => Promise<string | null>;
  readonly onEvent: (event: RealtimeDomainEvent, topic: string) => void;
  readonly socketFactory?: RealtimeSocketFactory;
}

export interface RealtimeClient {
  readonly enabled: boolean;
  start(): void;
  stop(): void;
  /** Ref-counted subscription; the returned function releases this holder. */
  subscribe(topic: RealtimeTopic): () => void;
  /** Reconnects when the in-memory access token is no longer the one in use. */
  reauthenticate(): void;
  getStatus(): RealtimeStatus;
  /** Observes the connection state; returns an unsubscribe function. */
  onStatus(listener: (status: RealtimeStatus) => void): () => void;
  /** Topics the client currently wants, whether or not the socket confirmed. */
  getTopics(): readonly RealtimeTopic[];
}

const defaultSocketFactory: RealtimeSocketFactory = (url, protocols) =>
  new WebSocket(url, protocols as string[]) as unknown as RealtimeSocketLike;

const backoffDelay = (attempt: number): number =>
  Math.min(INITIAL_RECONNECT_DELAY_MS * 2 ** attempt, MAX_RECONNECT_DELAY_MS);

export const createRealtimeClient = (options: RealtimeClientOptions): RealtimeClient => {
  const url = options.url.trim();
  const createSocket = options.socketFactory ?? defaultSocketFactory;

  // An empty endpoint is a supported deployment, not a fault: the client
  // reports itself disabled and never touches the network.
  if (url === '') {
    return {
      enabled: false,
      start: () => {},
      stop: () => {},
      subscribe: () => () => {},
      reauthenticate: () => {},
      getStatus: () => 'disabled',
      onStatus: () => () => {},
      getTopics: () => [],
    };
  }

  let status: RealtimeStatus = 'idle';
  let started = false;
  let socket: RealtimeSocketLike | null = null;
  /** Token the live (or in-flight) socket was opened with. */
  let socketToken: string | null = null;
  let attempt = 0;
  /** One renewal per refused handshake, so a dead session cannot spin. */
  let renewalTried = false;

  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let pongTimer: ReturnType<typeof setTimeout> | null = null;

  /** Holders per topic. A topic leaves the socket when the last one releases. */
  const holders = new Map<RealtimeTopic, number>();
  /** Topics the server has confirmed on the current connection. */
  const confirmed = new Set<RealtimeTopic>();
  /** Asked for on the current connection, not answered yet. */
  const pending = new Set<RealtimeTopic>();
  /** Topics the gateway refused; not retried until the next connection. */
  const refused = new Set<RealtimeTopic>();

  const statusListeners = new Set<(status: RealtimeStatus) => void>();

  const setStatus = (next: RealtimeStatus): void => {
    if (status === next) return;
    status = next;
    for (const listener of statusListeners) listener(next);
  };

  const clearTimer = (timer: ReturnType<typeof setTimeout> | null): null => {
    if (timer !== null) clearTimeout(timer);
    return null;
  };

  const stopHeartbeat = (): void => {
    if (heartbeatTimer !== null) clearInterval(heartbeatTimer);
    heartbeatTimer = null;
    pongTimer = clearTimer(pongTimer);
  };

  const sendFrame = (frame: unknown): void => {
    if (!socket || socket.readyState !== SOCKET_OPEN) return;
    socket.send(JSON.stringify(frame));
  };

  const detach = (target: RealtimeSocketLike): void => {
    target.onopen = null;
    target.onmessage = null;
    target.onclose = null;
    target.onerror = null;
  };

  const teardown = (code: number): void => {
    stopHeartbeat();
    confirmed.clear();
    pending.clear();
    refused.clear();
    if (!socket) return;
    const closing = socket;
    socket = null;
    detach(closing);
    closing.close(code);
  };

  // Assigned below: the reconnect timer and the close handler both call back
  // into it, so the binding has to exist before either is defined.
  let connect: () => void = () => {};

  const scheduleReconnect = (): void => {
    if (!started || reconnectTimer !== null) return;
    setStatus('reconnecting');
    const delay = backoffDelay(attempt);
    attempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const sendSubscribe = (topic: RealtimeTopic): void => {
    if (confirmed.has(topic) || pending.has(topic) || refused.has(topic)) return;
    // The gateway closes nothing over the limit — it answers with an error
    // frame — but a client that knows the cap simply does not ask.
    if (confirmed.size + pending.size >= MAX_SUBSCRIPTIONS_PER_CONNECTION) return;
    if (!socket || socket.readyState !== SOCKET_OPEN) return;
    pending.add(topic);
    sendFrame({ type: 'subscribe', topic });
  };

  const resubscribeAll = (): void => {
    for (const topic of holders.keys()) sendSubscribe(topic);
  };

  const startHeartbeat = (): void => {
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      // A previous ping is still unanswered: the socket is dead in one
      // direction, which no close event would tell us about.
      if (pongTimer !== null) return;
      sendFrame({ type: 'ping' });
      pongTimer = setTimeout(() => {
        pongTimer = null;
        teardown(CLOSE_CODE_NORMAL);
        scheduleReconnect();
      }, PONG_TIMEOUT_MS);
    }, HEARTBEAT_INTERVAL_MS);
  };

  const handleFrame = (text: string): void => {
    const frame = parseOutboundFrame(text);
    if (!frame) return;

    switch (frame.type) {
      case 'connected':
        // Authentication succeeded, so the backoff and the renewal budget both
        // start over for the next outage.
        attempt = 0;
        renewalTried = false;
        // The new connection carries no subscriptions: anything asked for
        // before the handshake finished never reached the gateway.
        confirmed.clear();
        pending.clear();
        refused.clear();
        setStatus('open');
        resubscribeAll();
        break;
      case 'subscribed':
        if (isRealtimeTopic(frame.topic)) {
          pending.delete(frame.topic);
          confirmed.add(frame.topic);
        }
        break;
      case 'unsubscribed':
        if (isRealtimeTopic(frame.topic)) {
          pending.delete(frame.topic);
          confirmed.delete(frame.topic);
        }
        break;
      case 'event': {
        const event = parseDomainEvent(frame.payload);
        if (event) options.onEvent(event, frame.topic);
        break;
      }
      case 'pong':
        pongTimer = clearTimer(pongTimer);
        break;
      case 'error':
        // A topic this account may not read is a fact about the account, not a
        // failure of the page: remember it and stop asking. The error frame
        // carries no topic, so everything still awaiting an answer is retired —
        // a confirmation for one of them would put it back.
        if (frame.code === REALTIME_ERROR_CODES.topicForbidden) {
          for (const topic of pending) refused.add(topic);
          pending.clear();
        }
        break;
    }
  };

  const handleClose = (code: number): void => {
    stopHeartbeat();
    socket = null;
    confirmed.clear();
    pending.clear();
    refused.clear();
    if (!started) {
      setStatus('idle');
      return;
    }

    // 1008 also covers a missed server-side heartbeat, so a refused handshake
    // is the case where no `connected` frame ever arrived.
    if (code === CLOSE_CODE_POLICY_VIOLATION && status !== 'open') {
      if (renewalTried) {
        setStatus('unauthorized');
        return;
      }
      renewalTried = true;
      void options.renewSession().then((token) => {
        if (!started) return;
        if (!token) {
          setStatus('unauthorized');
          return;
        }
        attempt = 0;
        connect();
      });
      setStatus('reconnecting');
      return;
    }

    scheduleReconnect();
  };

  connect = (): void => {
    if (!started || socket !== null) return;

    const token = options.getToken();
    if (!token) {
      // Nothing to authenticate with yet; the provider calls back in when the
      // session lands.
      setStatus('idle');
      return;
    }

    setStatus('connecting');
    socketToken = token;

    // A browser may only influence the handshake through the subprotocol, and
    // the gateway refuses to read a query string: a token there would end up in
    // every proxy access log.
    const opened = createSocket(url, [BEARER_SUBPROTOCOL, token]);
    socket = opened;

    opened.onopen = () => {
      startHeartbeat();
    };
    opened.onmessage = (event) => {
      if (typeof event.data === 'string') handleFrame(event.data);
    };
    opened.onclose = (event) => {
      if (socket !== opened) return;
      detach(opened);
      handleClose(event.code);
    };
    opened.onerror = () => {
      // `error` is always followed by `close`; the close handler owns recovery.
    };
  };

  return {
    enabled: true,

    start: () => {
      if (started) return;
      started = true;
      attempt = 0;
      renewalTried = false;
      connect();
    },

    stop: () => {
      started = false;
      reconnectTimer = clearTimer(reconnectTimer);
      teardown(CLOSE_CODE_NORMAL);
      setStatus('idle');
    },

    subscribe: (topic) => {
      const next = (holders.get(topic) ?? 0) + 1;
      holders.set(topic, next);
      if (next === 1) sendSubscribe(topic);

      let released = false;
      return () => {
        if (released) return;
        released = true;
        const remaining = (holders.get(topic) ?? 1) - 1;
        if (remaining > 0) {
          holders.set(topic, remaining);
          return;
        }
        holders.delete(topic);
        refused.delete(topic);
        pending.delete(topic);
        if (confirmed.delete(topic)) sendFrame({ type: 'unsubscribe', topic });
      };
    },

    reauthenticate: () => {
      if (!started) return;
      const token = options.getToken();
      if (!token || token === socketToken) return;
      // A renewed session invalidates nothing on the wire, but the next
      // handshake has to carry the new token, so the socket is replaced now
      // rather than at the far end of the 15-minute lifetime.
      renewalTried = false;
      attempt = 0;
      reconnectTimer = clearTimer(reconnectTimer);
      teardown(CLOSE_CODE_NORMAL);
      connect();
    },

    getStatus: () => status,

    onStatus: (listener) => {
      statusListeners.add(listener);
      return () => statusListeners.delete(listener);
    },

    getTopics: () => [...holders.keys()],
  };
};
