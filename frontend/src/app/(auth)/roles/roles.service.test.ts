import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RolesService } from './roles.service';
import { PERMISSION_CATALOGUE, grantsOutsideMatrix, isKnownPermission } from './roles.types';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const role = {
  id: 'r-1',
  name: 'admin',
  description: null,
  permissions: [{ resource: 'users', action: 'read', scope: 'ALL' }],
  createdAt: '2026-08-01T10:00:00.000Z',
  updatedAt: '2026-08-01T10:00:00.000Z',
};

const stubFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const call = (fetchMock: ReturnType<typeof stubFetch>) => {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : (JSON.parse(String(init.body)) as unknown),
  };
};

describe('RolesService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reads roles as a plain array, not a page', async () => {
    const fetchMock = stubFetch(json(200, { data: [role] }));

    await expect(RolesService.list()).resolves.toEqual([role]);
    expect(call(fetchMock).url).toContain('/rbac/roles');
  });

  it('omits an empty description — the create body is validated strictly', async () => {
    const fetchMock = stubFetch(json(201, { data: role }));

    await RolesService.create({ name: 'supervisor', permissions: [] });

    const { method, body } = call(fetchMock);
    expect(method).toBe('POST');
    expect(body).toEqual({ name: 'supervisor', permissions: [] });
  });

  it('keeps a description when one was given', async () => {
    const fetchMock = stubFetch(json(201, { data: role }));

    await RolesService.create({ name: 'supervisor', description: 'Нагляд', permissions: [] });

    expect(call(fetchMock).body).toEqual({
      name: 'supervisor',
      description: 'Нагляд',
      permissions: [],
    });
  });

  it('sends the whole set on replace, because the API substitutes rather than adds', async () => {
    const fetchMock = stubFetch(json(200, { data: role }));
    const permissions = [{ resource: 'users', action: 'read', scope: 'ALL' }] as const;

    await RolesService.replacePermissions('r-1', permissions);

    const { url, method, body } = call(fetchMock);
    expect(method).toBe('PUT');
    expect(url).toContain('/rbac/roles/r-1/permissions');
    expect(body).toEqual({ permissions: [{ resource: 'users', action: 'read', scope: 'ALL' }] });
  });

  it('checks a permission through its own endpoint', async () => {
    const fetchMock = stubFetch(json(200, { data: { allowed: true, scope: 'OWN' } }));

    await expect(RolesService.check('contacts', 'read')).resolves.toEqual({
      allowed: true,
      scope: 'OWN',
    });
    expect(call(fetchMock).url).toContain('/rbac/check/contacts/read');
  });
});

/**
 * The permission catalogue as both backends seed it (`prisma/seed.ts`,
 * `scripts/seed.py`). Copied here on purpose: when the API grows a module, this
 * list is what makes the missing matrix row a failing test instead of a role
 * that silently cannot be granted it.
 */
const SEEDED_PERMISSIONS = [
  'users:read',
  'users:create',
  'users:update',
  'users:disable',
  'contacts:read',
  'contacts:write',
  'contacts:delete',
  'deals:read',
  'deals:write',
  'deals:delete',
  'audit:read',
  'products:read',
  'products:write',
  'products:delete',
  'orders:read',
  'orders:write',
  'orders:delete',
  'warehouse:read',
  'warehouse:write',
  'settings:read',
  'settings:write',
  'analytics:read',
  'integrations:read',
  'integrations:write',
  'ai:use',
  'helpdesk:read',
  'helpdesk:write',
  'helpdesk:delete',
  'calls:read',
  'calls:write',
  'calls:delete',
  'finance:read',
  'finance:write',
];

describe('permission catalogue', () => {
  it('lists every permission the API seeds, without duplicates', () => {
    const keys = PERMISSION_CATALOGUE.map(([resource, action]) => `${resource}:${action}`);
    expect([...keys].sort()).toEqual([...SEEDED_PERMISSIONS].sort());
    expect(new Set(keys).size).toBe(keys.length);
  });

  // The PUT replaces the whole set: a grant the matrix cannot draw has to be
  // sent back as it was, or saving the role would revoke it.
  it('names the grants the matrix cannot show, so the editor keeps them', () => {
    const grants = [
      { resource: 'deals', action: 'read', scope: 'ALL' as const },
      { resource: 'reports', action: 'schedule', scope: 'OWN' as const },
    ];

    expect(grantsOutsideMatrix(grants)).toEqual([grants[1]]);
  });

  it('knows a real pair and refuses one the API would answer 400 for', () => {
    expect(isKnownPermission('users', 'disable')).toBe(true);
    // `users:write` does not exist: the users module splits create/update.
    expect(isKnownPermission('users', 'write')).toBe(false);
  });
});
