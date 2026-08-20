import { z } from 'zod';

/**
 * Mirrors the API's own rules so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */
export const loginSchema = z.object({
  email: z.email('Введіть коректну адресу'),
  password: z.string().min(1, 'Введіть пароль'),
});

export type LoginFormValues = z.infer<typeof loginSchema>;
