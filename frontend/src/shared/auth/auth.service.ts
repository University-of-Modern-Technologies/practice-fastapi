import { http, type AuthenticatedUser, type Session } from '@/shared/api';

export interface LoginInput {
  readonly email: string;
  readonly password: string;
}

const ROUTES = {
  login: '/auth/login',
  logout: '/auth/logout',
  me: '/auth/me',
} as const;

export const AuthService = {
  /** Marked anonymous so a wrong password never triggers a refresh attempt. */
  login: (input: LoginInput): Promise<Session> =>
    http.post<Session>(ROUTES.login, input, { anonymous: true }),

  logout: (): Promise<void> => http.post<void>(ROUTES.logout, undefined, { anonymous: true }),

  me: (): Promise<AuthenticatedUser> => http.get<AuthenticatedUser>(ROUTES.me),
};
