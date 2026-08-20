'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { setAccessToken, type Session } from '@/shared/api';
import { useAuthStore } from '@/shared/stores';
import { AuthService, type LoginInput } from './auth.service';

export const authKeys = {
  all: ['auth'] as const,
  me: () => [...authKeys.all, 'me'] as const,
};

export const applySession = (session: Session): void => {
  setAccessToken(session.accessToken);
  useAuthStore.getState().setSession(session);
};

export const clearSession = (): void => {
  setAccessToken(null);
  useAuthStore.getState().clearSession();
};

export const useLogin = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: LoginInput) => AuthService.login(input),
    onSuccess: (session) => {
      applySession(session);
      // The previous visitor's cached answers must not leak into this session.
      queryClient.clear();
    },
  });
};

export const useLogout = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => AuthService.logout(),
    // A failed logout still ends the session locally: leaving the user signed in
    // because the server call failed is the worse of the two outcomes.
    onSettled: () => {
      clearSession();
      queryClient.clear();
    },
  });
};
