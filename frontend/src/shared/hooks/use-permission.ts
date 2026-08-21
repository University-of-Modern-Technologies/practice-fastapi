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
