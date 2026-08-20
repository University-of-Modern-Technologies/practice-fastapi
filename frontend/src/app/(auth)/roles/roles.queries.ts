'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Id } from '@/types/domain';
import { RolesService } from './roles.service';
import type { CreateRoleInput, PermissionGrant, Role } from './roles.types';

export const rolesKeys = {
  all: ['roles'] as const,
  lists: () => [...rolesKeys.all, 'list'] as const,
  list: () => [...rolesKeys.lists()] as const,
};

export const useRoles = (enabled = true) =>
  useQuery<readonly Role[]>({
    queryKey: rolesKeys.list(),
    queryFn: () => RolesService.list(),
    enabled,
  });

export const useCreateRole = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateRoleInput) => RolesService.create(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: rolesKeys.lists() });
    },
  });
};

export const useReplaceRolePermissions = (roleId: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (permissions: readonly PermissionGrant[]) =>
      RolesService.replacePermissions(roleId, permissions),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: rolesKeys.lists() });
    },
  });
};
