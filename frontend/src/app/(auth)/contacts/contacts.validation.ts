import { z } from 'zod';
import type { ContactFormValues } from './contacts.types';

/**
 * An input the user never touched arrives as `undefined`; one they typed into
 * and emptied arrives as `''`. Both mean "not filled", so the schemas see the
 * same value in either case.
 */
const blankToUndefined = (value: unknown): unknown => {
  if (typeof value !== 'string') return value;
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
};

const blankToEmpty = (value: unknown): unknown => (typeof value === 'string' ? value.trim() : '');

const requiredText = (max: number, missing: string, tooLong: string) =>
  z.preprocess(blankToEmpty, z.string().min(1, missing).max(max, tooLong));

/**
 * Mirrors the API's own rules so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */
export const contactSchemas = {
  firstName: requiredText(80, 'Вкажіть імʼя', 'Імʼя — не більше 80 символів'),

  lastName: requiredText(80, 'Вкажіть прізвище', 'Прізвище — не більше 80 символів'),

  email: z.preprocess(
    blankToUndefined,
    z.email('Введіть коректну адресу').max(320, 'Пошта — не більше 320 символів').optional(),
  ),

  phone: z.preprocess(
    blankToUndefined,
    z.string().max(32, 'Телефон — не більше 32 символів').optional(),
  ),

  company: z.preprocess(
    blankToUndefined,
    z.string().max(160, 'Компанія — не більше 160 символів').optional(),
  ),

  notes: z.preprocess(blankToUndefined, z.string().optional()),
} as const;

/** Shown whenever the contact would end up with no way to reach the person. */
export const CONTACT_CHANNEL_MESSAGE = 'Вкажіть пошту або телефон';

/**
 * The API accepts a contact only with at least one channel. Checking it here
 * turns a rejected round trip into an inline message under the two fields it
 * actually concerns.
 */
export const hasContactChannel = (values: Partial<ContactFormValues>): boolean =>
  Boolean(values.email?.trim() || values.phone?.trim());
