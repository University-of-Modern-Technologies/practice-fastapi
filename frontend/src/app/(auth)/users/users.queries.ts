'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import type { Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import { UsersService } from './users.service';
import type { CreateUserInput, UpdateUserInput, User, UsersListQuery } from './users.types';

export const usersKeys = {
  all: ['users'] as const,
  lists: () => [...usersKeys.all, 'list'] as const,
  list: (query: UsersListQuery) => [...usersKeys.lists(), query] as const,
  details: () => [...usersKeys.all, 'detail'] as const,
  detail: (id: Id) => [...usersKeys.details(), id] as const,
};

export const useUsers = (query: UsersListQuery, enabled = true) =>
  useQuery<Page<User>>({
    queryKey: usersKeys.list(query),
    queryFn: () => UsersService.list(query),
    enabled,
  });

export const useUser = (id: Id) =>
  useQuery<User>({
    queryKey: usersKeys.detail(id),
    queryFn: () => UsersService.getById(id),
    enabled: Boolean(id),
  });

/** An account is named by its owner, and told apart by the address. */
export const userLabel = (user: User): string => `${user.name} · ${user.email}`;

/**
 * The users endpoint takes neither a search term nor a sort, so a picker reads
 * one page as large as the API allows and narrows it here. Beyond that page the
 * directory is not visible, and the notice below says so instead of pretending
 * the list is complete.
 */
const REFERENCE_PAGE: UsersListQuery = { page: 1, pageSize: 100 };

export const useUserOptions = (
  search: string,
): { items: readonly User[]; isFetching: boolean; notice?: string | undefined } => {
  const { data, isFetching } = useUsers(REFERENCE_PAGE);
  const term = search.trim().toLowerCase();

  const items = useMemo(() => {
    const rows = data?.items ?? [];
    return term === '' ? rows : rows.filter((user) => userLabel(user).toLowerCase().includes(term));
  }, [data, term]);

  const loaded = data?.items.length ?? 0;
  const total = data?.total ?? 0;

  return {
    items,
    isFetching,
    ...(total > loaded
      ? { notice: `Показано ${loaded} облікових записів із ${total} — пошук іде лише по них` }
      : {}),
  };
};

export const useResolvedUser = (id: Id | undefined): User | undefined => useUser(id ?? '').data;

export const useCreateUser = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateUserInput) => UsersService.create(input),
    onSuccess: (user) => {
      queryClient.setQueryData(usersKeys.detail(user.id), user);
      void queryClient.invalidateQueries({ queryKey: usersKeys.lists() });
    },
  });
};

export const useUpdateUser = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateUserInput) => UsersService.update(id, input),
    onSuccess: (user) => {
      queryClient.setQueryData(usersKeys.detail(id), user);
      void queryClient.invalidateQueries({ queryKey: usersKeys.lists() });
    },
  });
};

export const useDisableUser = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => UsersService.disable(id),
    onSuccess: (user) => {
      queryClient.setQueryData(usersKeys.detail(id), user);
      void queryClient.invalidateQueries({ queryKey: usersKeys.lists() });
    },
  });
};
