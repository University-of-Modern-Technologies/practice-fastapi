import { create } from 'zustand';
import type { AuthenticatedUser, PermissionScope, Session } from '@/shared/api';

/**
 * `unknown` is the state before the cookie-based session has been probed. The
 * shell must not redirect to the login page while in it, otherwise every reload
 * of a deep link would bounce the user out.
 */
export type AuthStatus = 'unknown' | 'anonymous' | 'authenticated';

interface AuthState {
  readonly status: AuthStatus;
  readonly user: AuthenticatedUser | null;
  setSession: (session: Session) => void;
  setUser: (user: AuthenticatedUser) => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'unknown',
  user: null,
  setSession: (session) => set({ status: 'authenticated', user: session.user }),
  setUser: (user) => set({ status: 'authenticated', user }),
  clearSession: () => set({ status: 'anonymous', user: null }),
}));

/**
 * Resolves the caller's grant for a `resource:action` pair, or null when there
 * is none. Hiding a control is a convenience for the user — the API enforces
 * the same rule on every request regardless of what the UI shows.
 */
export const permissionScope = (
  user: AuthenticatedUser | null,
  resource: string,
  action: string,
): PermissionScope | null => {
  const grant = user?.permissions.find(
    (candidate) => candidate.resource === resource && candidate.action === action,
  );
  return grant?.scope ?? null;
};
