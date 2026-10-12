'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { restoreSession, setAccessToken, type Session } from '@/shared/api';
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

/**
 * Probes the refresh cookie on a cold load, and again when the user asks to
 * retry. Never leaves the status at `unknown`: an anonymous visit becomes
 * `anonymous`, an API that could not answer becomes `unreachable`, and a live
 * session arrives through the `onSession` bridge.
 */
export const resumeSession = async (): Promise<void> => {
  try {
    const token = await restoreSession();
    if (!token) clearSession();
  } catch {
    useAuthStore.getState().markUnreachable();
  }
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
