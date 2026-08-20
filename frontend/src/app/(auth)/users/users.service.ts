import { http, type Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import type { CreateUserInput, UpdateUserInput, User, UsersListQuery } from './users.types';

const ROUTES = {
  list: '/users',
  byId: (id: Id) => `/users/${id}`,
  disable: (id: Id) => `/users/${id}/disable`,
} as const;

/**
 * The users endpoint takes no filters — only a page and a page size. Inventing
 * a `search` parameter here would send something the API silently ignores and
 * leave the user believing the list was narrowed.
 */
export const UsersService = {
  list: (query: UsersListQuery): Promise<Page<User>> =>
    http.get<Page<User>>(ROUTES.list, {
      params: { page: query.page, pageSize: query.pageSize },
    }),

  getById: (id: Id): Promise<User> => http.get<User>(ROUTES.byId(id)),

  create: (input: CreateUserInput): Promise<User> => http.post<User>(ROUTES.list, input),

  update: (id: Id, input: UpdateUserInput): Promise<User> =>
    http.patch<User>(ROUTES.byId(id), input),

  /** Accounts are switched off, never deleted: their history has to stay. */
  disable: (id: Id): Promise<User> => http.post<User>(ROUTES.disable(id)),
};
