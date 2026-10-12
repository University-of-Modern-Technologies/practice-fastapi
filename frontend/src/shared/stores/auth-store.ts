import { create } from 'zustand';
import type { AuthenticatedUser, PermissionScope, Session } from '@/shared/api';

/**
 * `unknown` is the state before the cookie-based session has been probed. The
 * shell must not redirect to the login page while in it, otherwise every reload
 * of a deep link would bounce the user out.
 *
 * `unreachable` means the probe itself failed — a 5xx or no connection. The
 * cookie may well be valid, so this is neither signed in nor signed out: the
 * shell offers to try again instead of a sign-in form or an endless skeleton.
 */
export type AuthStatus = 'unknown' | 'unreachable' | 'anonymous' | 'authenticated';

interface AuthState {
  readonly status: AuthStatus;
  readonly user: AuthenticatedUser | null;
  setSession: (session: Session) => void;
  setUser: (user: AuthenticatedUser) => void;
  clearSession: () => void;
  /** The session probe could not reach the API. */
  markUnreachable: () => void;
  /** A new probe is under way. */
  markChecking: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'unknown',
  user: null,
  setSession: (session) => set({ status: 'authenticated', user: session.user }),
  setUser: (user) => set({ status: 'authenticated', user }),
  clearSession: () => set({ status: 'anonymous', user: null }),
  markUnreachable: () => set({ status: 'unreachable', user: null }),
  markChecking: () => set({ status: 'unknown', user: null }),
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
