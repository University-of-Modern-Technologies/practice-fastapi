'use client';

import type { PermissionScope } from '@/shared/api';
import { permissionScope, useAuthStore } from '@/shared/stores';

/** Returns the caller's scope for `resource:action`, or null when denied. */
export const usePermissionScope = (resource: string, action: string): PermissionScope | null => {
  const user = useAuthStore((state) => state.user);
  return permissionScope(user, resource, action);
};

export const useHasPermission = (resource: string, action: string): boolean =>
  usePermissionScope(resource, action) !== null;

/**
 * Whether the caller may perform `resource:action` on one particular record.
 *
 * A grant is a scope, not a yes: `OWN` covers only records the caller owns,
 * and the API refuses the rest. A role can read every deal (`deals:read ALL`)
 * and still write only its own (`deals:write OWN`), so a control on someone
 * else's record has to be judged against its owner — otherwise it is offered
 * and then refused.
 *
 * `ownerId` left out means there is no record yet (a create button), and only
 * the grant itself matters. An unowned record (`null`) is not the caller's.
 */
export const useCanActOn = (
  resource: string,
  action: string,
  ownerId?: string | null | undefined,
): boolean => {
  const user = useAuthStore((state) => state.user);
  return canActOn(permissionScope(user, resource, action), user?.id, ownerId);
};

/** The rule behind `useCanActOn`, free of React so it can be read on its own. */
export const canActOn = (
  scope: PermissionScope | null,
  userId: string | undefined,
  ownerId?: string | null | undefined,
): boolean => {
  if (scope === null) return false;
  if (scope === 'ALL' || ownerId === undefined) return true;
  return ownerId !== null && ownerId === userId;
};
