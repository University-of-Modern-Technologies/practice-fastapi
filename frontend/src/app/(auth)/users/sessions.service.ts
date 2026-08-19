import { http } from '@/shared/api';
import type { Id } from '@/types/domain';
import type { UserSession } from './users.types';

const ROUTES = {
  list: (userId: Id) => `/users/${userId}/sessions`,
  byId: (userId: Id, sessionId: Id) => `/users/${userId}/sessions/${sessionId}`,
} as const;

/**
 * Sessions come back as a plain array rather than a page — the endpoint has no
 * paging, so the client must not pretend otherwise.
 */
export const UserSessionsService = {
  list: (userId: Id): Promise<readonly UserSession[]> =>
    http.get<readonly UserSession[]>(ROUTES.list(userId)),

  revoke: (userId: Id, sessionId: Id): Promise<void> =>
    http.delete<void>(ROUTES.byId(userId, sessionId)),
};
