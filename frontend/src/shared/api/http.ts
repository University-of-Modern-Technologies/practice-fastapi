import { ApiError, toApiError, toNetworkError } from './api-error';
import type { Envelope, Session } from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '/api/v1';

/**
 * The client holds the access token in memory only. The refresh token lives in
 * an httpOnly cookie the API sets, so a script injected into the page cannot
 * read either one and walk away with the session.
 */
let accessToken: string | null = null;

/** Notified whenever a session is established, renewed, or lost. */
type SessionListener = (session: Session | null) => void;

/**
 * A set rather than a single slot: the store bridge and the live-event channel
 * both need to hear about a renewal, and with one slot the second subscriber
 * would silently unhook the first.
 */
const sessionListeners = new Set<SessionListener>();

const onSessionChange = (session: Session | null): void => {
  for (const listener of sessionListeners) listener(session);
};

export const setAccessToken = (token: string | null): void => {
  accessToken = token;
};

export const getAccessToken = (): string | null => accessToken;

/** Subscribes to session changes and returns the matching unsubscribe. */
export const onSession = (listener: SessionListener): (() => void) => {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
};

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  readonly method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  readonly body?: unknown;
  readonly params?: Readonly<Record<string, QueryValue>>;
  readonly signal?: AbortSignal;
  /** Skips the refresh-and-retry cycle. Used by the auth calls themselves. */
  readonly anonymous?: boolean;
}

const buildUrl = (path: string, params?: Readonly<Record<string, QueryValue>>): string => {
  const url = `${API_URL}${path}`;
  if (!params) return url;

  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // An absent filter must not become the string "undefined" in the query.
    if (value === undefined || value === null || value === '') continue;
    search.append(key, String(value));
  }

  const query = search.toString();
  return query ? `${url}?${query}` : url;
};

const send = async (path: string, options: RequestOptions): Promise<Response> => {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (accessToken && !options.anonymous) headers.Authorization = `Bearer ${accessToken}`;

  try {
    return await fetch(buildUrl(path, options.params), {
      method: options.method ?? 'GET',
      headers,
      // Carries the refresh cookie; the API is the only origin that receives it.
      credentials: 'include',
      cache: 'no-store',
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    // An aborted request is the caller's own doing, not a transport failure.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw toNetworkError(cause);
  }
};

/**
 * In flight while a renewal is running. Concurrent 401s wait on this single
 * promise instead of each firing its own refresh, which would race and
 * invalidate one another's rotated token.
 */
let renewal: Promise<string | null> | null = null;

const renewSession = async (): Promise<string | null> => {
  const response = await send('/auth/refresh', { method: 'POST', anonymous: true });

  if (!response.ok) {
    setAccessToken(null);
    onSessionChange(null);
    return null;
  }

  const { data } = (await response.json()) as Envelope<Session>;
  setAccessToken(data.accessToken);
  onSessionChange(data);
  return data.accessToken;
};

const renewOnce = (): Promise<string | null> => {
  renewal ??= renewSession().finally(() => {
    renewal = null;
  });
  return renewal;
};

/** Restores a session from the refresh cookie on a cold page load. */
export const restoreSession = (): Promise<string | null> => renewOnce();

const parse = async <T>(response: Response): Promise<T> => {
  if (response.status === 204) return undefined as T;
  const { data } = (await response.json()) as Envelope<T>;
  return data;
};

/**
 * The 401-renew-and-retry cycle is the same regardless of what a successful
 * response turns into — a JSON envelope for ordinary calls, a blob for a file
 * download — so the two share this orchestration and differ only in `read`.
 */
const withRenewal = async <T>(
  path: string,
  options: RequestOptions,
  read: (response: Response) => Promise<T>,
): Promise<T> => {
  const response = await send(path, options);
  if (response.ok) return read(response);

  // Anything other than an expired access token is the caller's to handle.
  if (response.status !== 401 || options.anonymous) throw await toApiError(response);

  const renewed = await renewOnce();
  if (!renewed) throw await toApiError(response);

  // Exactly one retry: a second 401 means the renewed token is not the problem.
  const retried = await send(path, options);
  if (!retried.ok) {
    if (retried.status === 401) {
      setAccessToken(null);
      onSessionChange(null);
    }
    throw await toApiError(retried);
  }

  return read(retried);
};

const request = <T>(path: string, options: RequestOptions = {}): Promise<T> =>
  withRenewal(path, options, parse<T>);

/** A file the server named and typed, as opposed to a JSON envelope. */
export interface DownloadedFile {
  readonly blob: Blob;
  /** Null when the response carried no `Content-Disposition` at all. */
  readonly filename: string | null;
}

/**
 * Reads the name out of `Content-Disposition: attachment; filename="…"`. The
 * `filename*` form (RFC 5987) is preferred when present, since it is the one
 * that survives a non-ASCII report name.
 */
const filenameFromDisposition = (header: string | null): string | null => {
  if (!header) return null;

  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // Falls through to the plain form below.
    }
  }

  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header)?.[1];
  return plain ?? null;
};

const readFile = async (response: Response): Promise<DownloadedFile> => ({
  blob: await response.blob(),
  filename: filenameFromDisposition(response.headers.get('Content-Disposition')),
});

/**
 * A report export answers with a file, not the `{data}` envelope every other
 * route uses — `request` cannot read it, so this is the one place a response
 * body is taken as a blob instead of JSON.
 */
const downloadFile = (
  path: string,
  options: Omit<RequestOptions, 'method' | 'body'> = {},
): Promise<DownloadedFile> => withRenewal(path, { ...options, method: 'GET' }, readFile);

export const http = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>): Promise<T> =>
    request<T>(path, { ...options, method: 'GET' }),

  post: <T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> =>
    request<T>(path, { ...options, method: 'POST', body }),

  patch: <T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> =>
    request<T>(path, { ...options, method: 'PATCH', body }),

  put: <T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> =>
    request<T>(path, { ...options, method: 'PUT', body }),

  delete: <T = void>(path: string, options?: RequestOptions): Promise<T> =>
    request<T>(path, { ...options, method: 'DELETE' }),

  download: downloadFile,
};

export { ApiError };
