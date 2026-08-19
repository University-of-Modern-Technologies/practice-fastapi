'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Id } from '@/types/domain';
import { UserSessionsService } from './sessions.service';
import type { UserSession } from './users.types';

export const sessionsKeys = {
  all: ['user-sessions'] as const,
  lists: () => [...sessionsKeys.all, 'list'] as const,
  list: (userId: Id) => [...sessionsKeys.lists(), userId] as const,
};

export const useUserSessions = (userId: Id, enabled = true) =>
  useQuery<readonly UserSession[]>({
    queryKey: sessionsKeys.list(userId),
    queryFn: () => UserSessionsService.list(userId),
    enabled: enabled && Boolean(userId),
  });

export const useRevokeSession = (userId: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (sessionId: Id) => UserSessionsService.revoke(userId, sessionId),
    // The revoked row only changes in the answer to a re-read: the delete
    // returns 204 with no body to merge into the cache.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: sessionsKeys.list(userId) });
    },
  });
};
