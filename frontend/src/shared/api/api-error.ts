/**
 * Every failed call surfaces as this error. The client never reports a failure
 * through a return value: a request either resolves with data or throws, so a
 * caller cannot forget to check and treat a failure as success.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(params: {
    status: number;
    code: string;
    message: string;
    details?: unknown;
    requestId?: string | null;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.status = params.status;
    this.code = params.code;
    this.details = params.details ?? null;
    this.requestId = params.requestId ?? null;
  }

  /** The caller is not signed in, or the session has expired. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  /** The caller is signed in but lacks the permission for this action. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  /** Someone else changed the record first — the UI must offer a re-read. */
  get isConflict(): boolean {
    return this.status === 409;
  }

  get isValidation(): boolean {
    return this.status === 400 || this.status === 422;
  }
}

interface ErrorEnvelope {
  error?: { code?: unknown; message?: unknown; details?: unknown };
  requestId?: unknown;
}

const asString = (value: unknown): string | null => (typeof value === 'string' ? value : null);

/**
 * Builds an ApiError from a failed response. A body that is missing, malformed
 * or shaped differently (a proxy error page, for instance) must still produce a
 * usable error rather than a parsing crash.
 */
export const toApiError = async (response: Response): Promise<ApiError> => {
  let envelope: ErrorEnvelope | null = null;
  try {
    envelope = (await response.json()) as ErrorEnvelope;
  } catch {
    envelope = null;
  }

  return new ApiError({
    status: response.status,
    code: asString(envelope?.error?.code) ?? `HTTP_${response.status}`,
    message: asString(envelope?.error?.message) ?? (response.statusText || 'Request failed'),
    details: envelope?.error?.details,
    requestId: asString(envelope?.requestId),
  });
};

/** A transport-level failure: the request never reached the API. */
export const toNetworkError = (cause: unknown): ApiError =>
  new ApiError({
    status: 0,
    code: 'NETWORK_ERROR',
    message: cause instanceof Error ? cause.message : 'Network request failed',
  });
