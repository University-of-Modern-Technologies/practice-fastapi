import { z } from 'zod';

export const roleNameSchema = z
  .string()
  .trim()
  .min(1, 'Введіть назву ролі')
  .max(64, 'Не більше 64 символів');

export const roleDescriptionSchema = z.string().trim().max(255, 'Не більше 255 символів');

export const createRoleSchema = z.object({
  name: roleNameSchema,
  description: roleDescriptionSchema.optional(),
});
