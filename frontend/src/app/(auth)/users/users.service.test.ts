import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UserSessionsService } from './sessions.service';
import { UsersService } from './users.service';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const user = {
  id: 'u-1',
  email: 'a@b.c',
  name: 'Avery',
  isActive: true,
  roles: [{ id: 'r-1', name: 'admin' }],
  createdAt: '2026-08-01T10:00:00.000Z',
  updatedAt: '2026-08-01T10:00:00.000Z',
};

const stubFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

/** Request made by the call under test: url, method and parsed body. */
const call = (fetchMock: ReturnType<typeof stubFetch>) => {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : (JSON.parse(String(init.body)) as unknown),
  };
};

describe('UsersService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reads a page with only paging in the query — the API takes no filters', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { items: [user], page: 2, pageSize: 50, total: 51 } }),
    );

    const page = await UsersService.list({ page: 2, pageSize: 50 });

    expect(page.total).toBe(51);
    const { url, method } = call(fetchMock);
    expect(method).toBe('GET');
    expect(url).toContain('/users?');
    expect(url).toContain('page=2');
    expect(url).toContain('pageSize=50');
    expect(url).not.toContain('search');
  });

  it('unwraps a single user out of the envelope', async () => {
    const fetchMock = stubFetch(json(200, { data: user }));

    await expect(UsersService.getById('u-1')).resolves.toEqual(user);
    expect(call(fetchMock).url).toContain('/users/u-1');
  });

  it('creates a user with the role ids the API expects', async () => {
    const fetchMock = stubFetch(json(201, { data: user }));

    await UsersService.create({
      email: 'a@b.c',
      name: 'Avery',
      password: 'secret-1234',
      roleIds: ['r-1'],
    });

    const { url, method, body } = call(fetchMock);
    expect(method).toBe('POST');
    expect(url).toContain('/users');
    expect(body).toEqual({
      email: 'a@b.c',
      name: 'Avery',
      password: 'secret-1234',
      roleIds: ['r-1'],
    });
  });

  it('patches only the fields it was given', async () => {
    const fetchMock = stubFetch(json(200, { data: user }));

    await UsersService.update('u-1', { name: 'Avery A.' });

    const { url, method, body } = call(fetchMock);
    expect(method).toBe('PATCH');
    expect(url).toContain('/users/u-1');
    expect(body).toEqual({ name: 'Avery A.' });
  });

  it('disables through its own endpoint rather than a patch of isActive', async () => {
    const fetchMock = stubFetch(json(200, { data: { ...user, isActive: false } }));

    await expect(UsersService.disable('u-1')).resolves.toMatchObject({ isActive: false });

    const { url, method } = call(fetchMock);
    expect(method).toBe('POST');
    expect(url).toContain('/users/u-1/disable');
  });
});

describe('UserSessionsService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reads sessions as a plain array, not a page', async () => {
    const session = {
      id: 's-1',
      userId: 'u-1',
      expiresAt: '2026-08-20T10:00:00.000Z',
      revokedAt: null,
      ipAddress: '10.0.0.1',
      userAgent: 'Firefox',
      createdAt: '2026-08-01T10:00:00.000Z',
      updatedAt: '2026-08-01T10:00:00.000Z',
    };
    const fetchMock = stubFetch(json(200, { data: [session] }));

    const sessions = await UserSessionsService.list('u-1');

    expect(sessions).toEqual([session]);
    expect(call(fetchMock).url).toContain('/users/u-1/sessions');
  });

  it('revokes a session and tolerates the empty 204 body', async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(UserSessionsService.revoke('u-1', 's-1')).resolves.toBeUndefined();

    const { url, method } = call(fetchMock);
    expect(method).toBe('DELETE');
    expect(url).toContain('/users/u-1/sessions/s-1');
  });
});
