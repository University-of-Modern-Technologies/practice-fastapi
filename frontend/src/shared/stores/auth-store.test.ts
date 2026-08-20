import { describe, expect, it } from 'vitest';
import type { AuthenticatedUser } from '@/shared/api';
import { permissionScope } from './auth-store';

const user: AuthenticatedUser = {
  id: 'u1',
  email: 'manager@example.com',
  name: 'Manager',
  roles: ['manager'],
  permissions: [
    { resource: 'contacts', action: 'read', scope: 'OWN' },
    { resource: 'contacts', action: 'write', scope: 'OWN' },
    { resource: 'products', action: 'read', scope: 'ALL' },
  ],
};

describe('permissionScope', () => {
  it('returns the granted scope', () => {
    expect(permissionScope(user, 'contacts', 'read')).toBe('OWN');
    expect(permissionScope(user, 'products', 'read')).toBe('ALL');
  });

  it('refuses an action that was never granted', () => {
    expect(permissionScope(user, 'contacts', 'delete')).toBeNull();
    expect(permissionScope(user, 'audit', 'read')).toBeNull();
  });

  it('does not confuse a resource with an action of the same name', () => {
    expect(permissionScope(user, 'read', 'contacts')).toBeNull();
  });

  it('treats an unknown caller as having no rights at all', () => {
    expect(permissionScope(null, 'products', 'read')).toBeNull();
  });
});
