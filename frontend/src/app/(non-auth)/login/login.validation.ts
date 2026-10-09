import { z } from 'zod';

/** The bounds `POST /auth/login` declares for a password. */
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;

/**
 * Mirrors the API's own rules so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip,
 * and a password the API would refuse outright answers here, under the field,
 * instead of as a generic "could not sign in".
 */
export const loginSchema = z.object({
  email: z.email('Введіть коректну адресу'),
  password: z
    .string()
    .min(1, 'Введіть пароль')
    .min(PASSWORD_MIN_LENGTH, `Пароль — щонайменше ${PASSWORD_MIN_LENGTH} символів`)
    .max(PASSWORD_MAX_LENGTH, `Пароль — не більше ${PASSWORD_MAX_LENGTH} символів`),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

/**
 * Where to go after signing in, reduced to a path on this very site.
 *
 * Checking the raw text — "starts with one slash, not two" — is not enough:
 * the URL parser drops tabs and newlines and reads a backslash as a slash, so
 * `/\t/evil.example` and `/\evil.example` both pass such a check and still
 * land on another host. The value is therefore resolved the way the browser
 * will resolve it, and only a result on the same origin is kept.
 */
export const safeNext = (value: string | null, origin: string): string => {
  if (!value) return '/';

  let target: URL;
  try {
    target = new URL(value, origin);
  } catch {
    return '/';
  }

  if (target.origin !== new URL(origin).origin) return '/';
  return `${target.pathname}${target.search}${target.hash}`;
};
