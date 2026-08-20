import { http } from '@/shared/api';
import type { Id } from '@/types/domain';
import type { CreateRoleInput, PermissionCheck, PermissionGrant, Role } from './roles.types';

const ROUTES = {
  roles: '/rbac/roles',
  rolePermissions: (id: Id) => `/rbac/roles/${id}/permissions`,
  check: (resource: string, action: string) => `/rbac/check/${resource}/${action}`,
} as const;

export const RolesService = {
  /** Roles come back as a plain array: the endpoint has no paging. */
  list: (): Promise<readonly Role[]> => http.get<readonly Role[]>(ROUTES.roles),

  /**
   * The body is validated strictly — an extra field is rejected outright, so an
   * empty description is omitted rather than sent as an empty string.
   */
  create: (input: CreateRoleInput): Promise<Role> =>
    http.post<Role>(ROUTES.roles, {
      name: input.name,
      ...(input.description ? { description: input.description } : {}),
      permissions: input.permissions,
    }),

  /**
   * Replaces the whole set. Anything missing from `permissions` is taken away
   * from the role — this is not an addition.
   */
  replacePermissions: (id: Id, permissions: readonly PermissionGrant[]): Promise<Role> =>
    http.put<Role>(ROUTES.rolePermissions(id), { permissions }),

  check: (resource: string, action: string): Promise<PermissionCheck> =>
    http.get<PermissionCheck>(ROUTES.check(resource, action)),
};
