import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as HttpModule from './http';

type Http = typeof HttpModule;

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const session = (accessToken: string) => ({
  data: {
    accessToken,
    accessTokenExpiresInSeconds: 900,
    user: { id: 'u1', email: 'a@b.c', name: 'A', roles: [], permissions: [] },
  },
});

/** Module state (token, in-flight renewal) must not leak between cases. */
const loadHttp = async (): Promise<Http> => {
  vi.resetModules();
  return import('./http');
};

describe('http client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('returns the payload out of the envelope', async () => {
    const { http } = await loadHttp();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json(200, { data: { id: '1', name: 'Contact' } })),
    );

    await expect(http.get('/contacts/1')).resolves.toEqual({ id: '1', name: 'Contact' });
  });

  it('throws an ApiError carrying the code and the request id', async () => {
    const { ApiError, http } = await loadHttp();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        json(409, {
          error: { code: 'VERSION_CONFLICT', message: 'Stale version' },
          requestId: 'req-7',
        }),
      ),
    );

    const error = await http.patch('/contacts/1', {}).catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'VERSION_CONFLICT', requestId: 'req-7' });
    expect((error as InstanceType<typeof ApiError>).isConflict).toBe(true);
  });

  it('still produces a usable error when the body is not the expected shape', async () => {
    const { ApiError, http } = await loadHttp();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 502 })),
    );

    const error = (await http.get('/contacts').catch((cause: unknown) => cause)) as InstanceType<
      typeof ApiError
    >;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.code).toBe('HTTP_502');
  });

  it('renews the session once and retries the original request', async () => {
    const { http, setAccessToken } = await loadHttp();
    setAccessToken('expired');

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: 'UNAUTHORIZED', message: 'expired' } }))
      .mockResolvedValueOnce(json(200, session('fresh')))
      .mockResolvedValueOnce(json(200, { data: { id: '1' } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(http.get('/contacts/1')).resolves.toEqual({ id: '1' });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/auth/refresh');
    // The retry must carry the token the renewal produced, not the expired one.
    const retryHeaders = (fetchMock.mock.calls[2]?.[1] as RequestInit).headers as Record<
      string,
      string
    >;
    expect(retryHeaders.Authorization).toBe('Bearer fresh');
  });

  it('renews only once when several requests meet a 401 together', async () => {
    const { http, setAccessToken } = await loadHttp();
    setAccessToken('expired');

    // Both requests meet a 401 on the first pass; once the renewal lands, both
    // retries succeed. Only one renewal may be issued for the pair.
    let renewed = false;
    const smartFetch = vi.fn((input: string) => {
      if (input.includes('/auth/refresh')) {
        renewed = true;
        return Promise.resolve(json(200, session('fresh')));
      }
      return Promise.resolve(
        renewed
          ? json(200, { data: { ok: true } })
          : json(401, { error: { code: 'UNAUTHORIZED' } }),
      );
    });
    vi.stubGlobal('fetch', smartFetch);

    await Promise.all([http.get('/contacts'), http.get('/deals')]);

    const refreshCalls = smartFetch.mock.calls.filter(([url]) => url.includes('/auth/refresh'));
    expect(refreshCalls).toHaveLength(1);
  });

  it('drops the session when the renewal itself is refused', async () => {
    const { getAccessToken, http, onSession, setAccessToken } = await loadHttp();
    setAccessToken('expired');
    const listener = vi.fn();
    onSession(listener);

    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(json(401, { error: { code: 'UNAUTHORIZED' } }))
        .mockResolvedValueOnce(json(401, { error: { code: 'REFRESH_TOKEN_REQUIRED' } })),
    );

    await expect(http.get('/contacts')).rejects.toBeInstanceOf(Error);

    expect(getAccessToken()).toBeNull();
    expect(listener).toHaveBeenCalledWith(null);
  });

  it('reads a downloaded file as a blob and names it from the response header', async () => {
    const { http } = await loadHttp();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('a,b\n1,2', {
          status: 200,
          headers: {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': 'attachment; filename="sales-summary.csv"',
          },
        }),
      ),
    );

    const file = await http.download('/analytics/sales-summary/export', {
      params: { format: 'csv' },
    });

    expect(file.filename).toBe('sales-summary.csv');
    // jsdom's Blob does not implement `.text()`; size is what is left to assert on.
    expect(file.blob).toBeInstanceOf(Blob);
    expect(file.blob.size).toBe('a,b\n1,2'.length);
  });

  it('prefers the UTF-8 encoded filename form when the header carries one', async () => {
    const { http } = await loadHttp();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('', {
          status: 200,
          headers: {
            'Content-Disposition': "attachment; filename*=UTF-8''%D0%B7%D0%B2%D1%96%D1%82.csv",
          },
        }),
      ),
    );

    const file = await http.download('/analytics/sales-summary/export');

    expect(file.filename).toBe('звіт.csv');
  });

  it('falls back to a null filename when the response carries no header', async () => {
    const { http } = await loadHttp();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 200 })));

    const file = await http.download('/analytics/sales-summary/export');

    expect(file.filename).toBeNull();
  });

  it('renews the session once and retries a download the same way as a JSON request', async () => {
    const { http, setAccessToken } = await loadHttp();
    setAccessToken('expired');

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: 'UNAUTHORIZED', message: 'expired' } }))
      .mockResolvedValueOnce(json(200, session('fresh')))
      .mockResolvedValueOnce(
        new Response('x', {
          status: 200,
          headers: { 'Content-Disposition': 'attachment; filename="stock-health.csv"' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const file = await http.download('/analytics/stock-health/export');

    expect(file.filename).toBe('stock-health.csv');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('throws the API error and never touches the body as a blob on a failed download', async () => {
    const { ApiError, http } = await loadHttp();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json(500, { error: { code: 'INTERNAL', message: 'boom' } })),
    );

    const error = await http
      .download('/analytics/sales-summary/export')
      .catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as InstanceType<typeof ApiError>).code).toBe('INTERNAL');
  });

  it('omits empty filters from the query string', async () => {
    const { http } = await loadHttp();
    const fetchMock = vi.fn().mockResolvedValue(json(200, { data: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await http.get('/contacts', {
      params: { page: 1, search: '', ownerId: undefined, active: false },
    });

    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain('page=1');
    expect(url).toContain('active=false');
    expect(url).not.toContain('search');
    expect(url).not.toContain('ownerId');
  });
});
