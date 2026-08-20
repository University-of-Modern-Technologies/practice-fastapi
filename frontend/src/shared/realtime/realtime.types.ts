/**
 * Wire contract of the realtime channel. Mirrors the frames the API gateway
 * accepts and emits; nothing here talks to React or to the query cache.
 */

/** Marker subprotocol. The token travels as the second subprotocol value. */
export const BEARER_SUBPROTOCOL = 'bearer';

/** Sent by the server when it shuts down gracefully. */
export const CLOSE_CODE_GOING_AWAY = 1001;

/** Sent on a failed handshake and on a missed heartbeat. */
export const CLOSE_CODE_POLICY_VIOLATION = 1008;

/** Used by the client itself when it tears a socket down on purpose. */
export const CLOSE_CODE_NORMAL = 1000;

/** Hard cap the gateway puts on a single inbound frame. */
export const MAX_INBOUND_FRAME_BYTES = 8 * 1024;

export const REALTIME_ERROR_CODES = {
  invalidMessage: 'INVALID_MESSAGE',
  messageTooLarge: 'MESSAGE_TOO_LARGE',
  unknownTopic: 'UNKNOWN_TOPIC',
  topicForbidden: 'TOPIC_FORBIDDEN',
  subscriptionLimit: 'SUBSCRIPTION_LIMIT_REACHED',
  notSubscribed: 'NOT_SUBSCRIBED',
  internal: 'INTERNAL_ERROR',
} as const;

export type RealtimeErrorCode = (typeof REALTIME_ERROR_CODES)[keyof typeof REALTIME_ERROR_CODES];

export type InboundFrame =
  | { readonly type: 'subscribe'; readonly topic: string }
  | { readonly type: 'unsubscribe'; readonly topic: string }
  | { readonly type: 'ping' };

export type OutboundFrame =
  | { readonly type: 'connected'; readonly connectionId: string; readonly userId: string }
  | { readonly type: 'subscribed'; readonly topic: string }
  | { readonly type: 'unsubscribed'; readonly topic: string }
  | { readonly type: 'event'; readonly topic: string; readonly payload: unknown }
  | { readonly type: 'pong' }
  | { readonly type: 'error'; readonly code: RealtimeErrorCode; readonly message: string };

/**
 * Body of an `event` frame. The gateway forwards the domain event verbatim, so
 * `payload` is whatever the producing module attached and stays `unknown` until
 * a consumer decides what it wants from it.
 */
export interface RealtimeDomainEvent {
  readonly eventType: string;
  readonly entityType: string;
  readonly entityId: string;
  readonly actorId: string | null;
  readonly payload: unknown;
}

export type RealtimeStatus =
  /** `NEXT_PUBLIC_WS_URL` is empty — the channel is off by configuration. */
  | 'disabled'
  /** Created but not started, or stopped after a sign-out. */
  | 'idle'
  | 'connecting'
  | 'open'
  /** Waiting out the backoff before the next attempt. */
  | 'reconnecting'
  /** The handshake was refused and renewing the session did not help. */
  | 'unauthorized';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const isErrorCode = (value: unknown): value is RealtimeErrorCode =>
  typeof value === 'string' &&
  (Object.values(REALTIME_ERROR_CODES) as readonly string[]).includes(value);

/**
 * Narrows a decoded frame. Anything that does not match the published shape is
 * dropped rather than trusted: a frame the client cannot name is a frame it
 * cannot act on.
 */
export const parseOutboundFrame = (text: string): OutboundFrame | null => {
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch {
    return null;
  }

  if (!isRecord(json)) return null;

  switch (json.type) {
    case 'connected':
      return typeof json.connectionId === 'string' && typeof json.userId === 'string'
        ? { type: 'connected', connectionId: json.connectionId, userId: json.userId }
        : null;
    case 'subscribed':
      return typeof json.topic === 'string' ? { type: 'subscribed', topic: json.topic } : null;
    case 'unsubscribed':
      return typeof json.topic === 'string' ? { type: 'unsubscribed', topic: json.topic } : null;
    case 'event':
      return typeof json.topic === 'string'
        ? { type: 'event', topic: json.topic, payload: json.payload }
        : null;
    case 'pong':
      return { type: 'pong' };
    case 'error':
      return isErrorCode(json.code) && typeof json.message === 'string'
        ? { type: 'error', code: json.code, message: json.message }
        : null;
    default:
      return null;
  }
};

/** Narrows the payload of an `event` frame onto the domain event shape. */
export const parseDomainEvent = (payload: unknown): RealtimeDomainEvent | null => {
  if (!isRecord(payload)) return null;

  const { eventType, entityType, entityId, actorId } = payload;
  if (typeof eventType !== 'string' || eventType === '') return null;
  if (typeof entityType !== 'string' || typeof entityId !== 'string') return null;

  return {
    eventType,
    entityType,
    entityId,
    actorId: typeof actorId === 'string' ? actorId : null,
    payload: payload.payload ?? null,
  };
};
