import { z } from 'zod';

/**
 * Mirrors the API's own rules field by field, so an obviously wrong form never
 * becomes a request. The server validates independently — this saves a round
 * trip, it does not replace the check.
 */
export const userEmailSchema = z.email('Введіть коректну адресу');

export const userNameSchema = z
  .string()
  .trim()
  .min(1, 'Введіть імʼя')
  .max(120, 'Не більше 120 символів');

export const userPasswordSchema = z
  .string()
  .min(8, 'Щонайменше 8 символів')
  .max(128, 'Не більше 128 символів');

export const userRoleIdsSchema = z
  .array(z.string())
  .min(1, 'Оберіть щонайменше одну роль')
  .max(20, 'Не більше 20 ролей');

/** A new account always sets a password; an existing one changes it optionally. */
export const createUserSchema = z.object({
  email: userEmailSchema,
  name: userNameSchema,
  password: userPasswordSchema,
  roleIds: userRoleIdsSchema,
});

export const updateUserSchema = createUserSchema.extend({
  password: userPasswordSchema.optional(),
});
