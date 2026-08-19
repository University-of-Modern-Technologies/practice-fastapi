import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createRealtimeClient,
  type RealtimeClient,
  type RealtimeSocketLike,
} from './realtime.client';
import { MAX_SUBSCRIPTIONS_PER_CONNECTION, type RealtimeTopic } from './realtime.topics';
import type { RealtimeDomainEvent } from './realtime.types';

/** Fake transport. Every frame the client writes lands in `sent`. */
class FakeSocket implements RealtimeSocketLike {
  /** Starts CONNECTING, like the real thing: a frame sent now is lost. */
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { readonly data: unknown }) => void) | null = null;
  onclose: ((event: { readonly code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  readonly sent: string[] = [];
  closedWith: number | null = null;

  constructor(
    readonly url: string,
    readonly protocols: readonly string[],
  ) {}

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number): void {
    this.readyState = 3;
    this.closedWith = code ?? null;
  }

  /** Drives the handshake the way a real socket would. */
  open(userId = 'user-1'): void {
    this.readyState = 1;
    this.onopen?.();
    this.receive({ type: 'connected', connectionId: 'c-1', userId });
  }

  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  fireClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  frames(): unknown[] {
    return this.sent.map((raw) => JSON.parse(raw) as unknown);
  }
}

interface Harness {
  readonly client: RealtimeClient;
  readonly sockets: FakeSocket[];
  readonly events: RealtimeDomainEvent[];
  readonly renewals: number;
  last(): FakeSocket;
}

const createHarness = (
  overrides: {
    readonly url?: string;
    readonly token?: string | null;
    readonly renewedToken?: string | null;
  } = {},
): Harness => {
  const sockets: FakeSocket[] = [];
  const events: RealtimeDomainEvent[] = [];
  const state = { token: overrides.token === undefined ? 'token-1' : overrides.token, renewals: 0 };

  const client = createRealtimeClient({
    url: overrides.url ?? 'ws://localhost:3000/ws',
    getToken: () => state.token,
    renewSession: () => {
      state.renewals += 1;
      const renewed = overrides.renewedToken ?? null;
      state.token = renewed;
      return Promise.resolve(renewed);
    },
    onEvent: (event) => events.push(event),
    socketFactory: (url, protocols) => {
      const socket = new FakeSocket(url, protocols);
      sockets.push(socket);
      return socket;
    },
  });

  return {
    client,
    sockets,
    events,
    get renewals() {
      return state.renewals;
    },
    last: () => {
      const socket = sockets.at(-1);
      if (!socket) throw new Error('no socket was created');
      return socket;
    },
  };
};

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('createRealtimeClient — disabled channel', () => {
  it('never opens a socket when the endpoint is empty', () => {
    const harness = createHarness({ url: '' });

    harness.client.start();
    harness.client.subscribe('deals');

    expect(harness.client.enabled).toBe(false);
    expect(harness.client.getStatus()).toBe('disabled');
    expect(harness.sockets).toHaveLength(0);
  });

  it('treats whitespace as an empty endpoint', () => {
    expect(createHarness({ url: '   ' }).client.enabled).toBe(false);
  });
});

describe('createRealtimeClient — handshake', () => {
  it('carries the token as the bearer subprotocol, never in the URL', () => {
    const harness = createHarness();
    harness.client.start();

    const socket = harness.last();
    expect(socket.protocols).toEqual(['bearer', 'token-1']);
    expect(socket.url).toBe('ws://localhost:3000/ws');
    expect(socket.url).not.toContain('token-1');
  });

  it('stays idle while there is no token to present', () => {
    const harness = createHarness({ token: null });
    harness.client.start();

    expect(harness.sockets).toHaveLength(0);
    expect(harness.client.getStatus()).toBe('idle');
  });

  it('reports open only after the connected frame', () => {
    const harness = createHarness();
    harness.client.start();
    expect(harness.client.getStatus()).toBe('connecting');

    harness.last().open();
    expect(harness.client.getStatus()).toBe('open');
  });
});

describe('createRealtimeClient — subscriptions', () => {
  it('replays every wanted topic after a reconnect', () => {
    const harness = createHarness();
    harness.client.start();
    harness.client.subscribe('deals');
    harness.client.subscribe('entity:deal:abc');

    const first = harness.last();
    first.open();
    expect(first.frames()).toEqual([
      { type: 'subscribe', topic: 'deals' },
      { type: 'subscribe', topic: 'entity:deal:abc' },
    ]);

    first.receive({ type: 'subscribed', topic: 'deals' });
    first.fireClose(1006);
    vi.advanceTimersByTime(1_000);

    const second = harness.last();
    second.open();
    expect(second.frames()).toEqual([
      { type: 'subscribe', topic: 'deals' },
      { type: 'subscribe', topic: 'entity:deal:abc' },
    ]);
  });

  it('counts holders and only unsubscribes when the last one releases', () => {
    const harness = createHarness();
    harness.client.start();
    const socket = harness.last();
    socket.open();

    const releaseA = harness.client.subscribe('orders');
    const releaseB = harness.client.subscribe('orders');
    socket.receive({ type: 'subscribed', topic: 'orders' });

    expect(socket.frames()).toEqual([{ type: 'subscribe', topic: 'orders' }]);

    releaseA();
    expect(socket.frames()).toHaveLength(1);

    releaseB();
    expect(socket.frames()).toEqual([
      { type: 'subscribe', topic: 'orders' },
      { type: 'unsubscribe', topic: 'orders' },
    ]);
  });

  it('stops at the connection limit instead of asking for a refusal', () => {
    const harness = createHarness();
    harness.client.start();
    const socket = harness.last();
    socket.open();

    for (let index = 0; index < MAX_SUBSCRIPTIONS_PER_CONNECTION + 5; index += 1) {
      const topic = `entity:deal:id-${String(index)}` as RealtimeTopic;
      harness.client.subscribe(topic);
      socket.receive({ type: 'subscribed', topic });
    }

    expect(socket.frames()).toHaveLength(MAX_SUBSCRIPTIONS_PER_CONNECTION);
    expect(harness.client.getTopics()).toHaveLength(MAX_SUBSCRIPTIONS_PER_CONNECTION + 5);
  });

  it('does not retry a topic the gateway forbids', () => {
    const harness = createHarness();
    harness.client.start();
    const socket = harness.last();
    socket.open();

    harness.client.subscribe('deals');
    socket.receive({ type: 'error', code: 'TOPIC_FORBIDDEN', message: 'nope' });

    // A second holder of the same topic does not ask the gateway again.
    harness.client.subscribe('deals');
    expect(socket.frames()).toEqual([{ type: 'subscribe', topic: 'deals' }]);

    // The refusal is per connection: a fresh one asks once more, because the
    // grant may have been widened in the meantime.
    socket.fireClose(1006);
    vi.advanceTimersByTime(1_000);
    const reconnected = harness.last();
    reconnected.open();
    expect(reconnected.frames()).toEqual([{ type: 'subscribe', topic: 'deals' }]);
  });
});

describe('createRealtimeClient — frames', () => {
  it('forwards a domain event and ignores malformed ones', () => {
    const harness = createHarness();
    harness.client.start();
    const socket = harness.last();
    socket.open();

    socket.receive({
      type: 'event',
      topic: 'deals',
      payload: {
        eventType: 'deal.updated',
        entityType: 'deal',
        entityId: 'd-1',
        actorId: 'u-1',
        payload: { stage: 'WON' },
      },
    });
    socket.receive({ type: 'event', topic: 'deals', payload: { eventType: 'deal.updated' } });
    socket.onmessage?.({ data: 'not json' });
    socket.receive({ type: 'nonsense' });

    expect(harness.events).toEqual([
      {
        eventType: 'deal.updated',
        entityType: 'deal',
        entityId: 'd-1',
        actorId: 'u-1',
        payload: { stage: 'WON' },
      },
    ]);
  });
});

describe('createRealtimeClient — heartbeat', () => {
  it('pings ahead of the server timeout and reconnects on a missing pong', () => {
    const harness = createHarness();
    harness.client.start();
    const socket = harness.last();
    socket.open();

    vi.advanceTimersByTime(15_000);
    expect(socket.frames()).toEqual([{ type: 'ping' }]);

    socket.receive({ type: 'pong' });
    vi.advanceTimersByTime(15_000);
    expect(socket.frames()).toHaveLength(2);

    // No pong this time: the socket is dropped and a new one is scheduled.
    vi.advanceTimersByTime(10_000);
    expect(socket.closedWith).toBe(1000);

    vi.advanceTimersByTime(1_000);
    expect(harness.sockets).toHaveLength(2);
  });
});

describe('createRealtimeClient — reconnection', () => {
  it('backs off exponentially up to the ceiling', () => {
    const harness = createHarness();
    harness.client.start();

    const expected = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000];
    expected.forEach((delay, index) => {
      harness.last().fireClose(1006);
      expect(harness.client.getStatus()).toBe('reconnecting');

      vi.advanceTimersByTime(delay - 1);
      expect(harness.sockets).toHaveLength(index + 1);

      vi.advanceTimersByTime(1);
      expect(harness.sockets).toHaveLength(index + 2);
    });
  });

  it('resets the backoff once a connection succeeds', () => {
    const harness = createHarness();
    harness.client.start();

    harness.last().fireClose(1006);
    vi.advanceTimersByTime(1_000);
    harness.last().open();

    harness.last().fireClose(1001);
    vi.advanceTimersByTime(1_000);
    expect(harness.sockets).toHaveLength(3);
  });

  it('stops scheduling anything after stop()', () => {
    const harness = createHarness();
    harness.client.start();
    harness.last().open();
    harness.client.stop();

    expect(harness.client.getStatus()).toBe('idle');
    vi.advanceTimersByTime(120_000);
    expect(harness.sockets).toHaveLength(1);
  });
});

describe('createRealtimeClient — refused handshake', () => {
  it('renews the session once and reconnects with the new token', async () => {
    const harness = createHarness({ renewedToken: 'token-2' });
    harness.client.start();
    harness.last().fireClose(1008);

    await vi.runAllTimersAsync();

    expect(harness.renewals).toBe(1);
    expect(harness.sockets).toHaveLength(2);
    expect(harness.last().protocols).toEqual(['bearer', 'token-2']);
  });

  it('gives up instead of looping when the renewal fails', async () => {
    const harness = createHarness({ renewedToken: null });
    harness.client.start();
    harness.last().fireClose(1008);

    await vi.runAllTimersAsync();

    expect(harness.renewals).toBe(1);
    expect(harness.sockets).toHaveLength(1);
    expect(harness.client.getStatus()).toBe('unauthorized');
  });

  it('treats 1008 on a live connection as an ordinary drop', () => {
    const harness = createHarness({ renewedToken: 'token-2' });
    harness.client.start();
    harness.last().open();

    // A missed server heartbeat closes with the same code; the session is fine.
    harness.last().fireClose(1008);
    vi.advanceTimersByTime(1_000);

    expect(harness.renewals).toBe(0);
    expect(harness.sockets).toHaveLength(2);
  });
});

describe('createRealtimeClient — reauthenticate', () => {
  it('replaces the socket when the in-memory token changed', () => {
    const sockets: FakeSocket[] = [];
    let token = 'token-1';

    const client = createRealtimeClient({
      url: 'ws://localhost:3000/ws',
      getToken: () => token,
      renewSession: () => Promise.resolve(null),
      onEvent: () => {},
      socketFactory: (url, protocols) => {
        const socket = new FakeSocket(url, protocols);
        sockets.push(socket);
        return socket;
      },
    });

    client.start();
    sockets[0]?.open();

    client.reauthenticate();
    expect(sockets).toHaveLength(1);

    token = 'token-2';
    client.reauthenticate();
    expect(sockets).toHaveLength(2);
    expect(sockets[1]?.protocols).toEqual(['bearer', 'token-2']);
  });
});
