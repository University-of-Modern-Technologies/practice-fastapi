import { z } from 'zod';

/**
 * Mirrors the rules the API enforces so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */

/** A comma is allowed on input because that is how the amount is typed here. */
const AMOUNT_PATTERN = /^\d{1,12}(?:[.,]\d{1,2})?$/;

const UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** Optional links to the owner, the contact and the deal are all identifiers. */
export const orderReferenceSchema = z
  .string()
  .trim()
  .regex(UUID_PATTERN, 'Вкажіть коректний ідентифікатор')
  .optional()
  .or(z.literal(''));

export const orderProductSchema = z
  .string()
  .trim()
  .min(1, 'Оберіть товар')
  .regex(UUID_PATTERN, 'Вкажіть коректний ідентифікатор товару');

export const orderCurrencySchema = z
  .string()
  .trim()
  .regex(/^[A-Za-z]{3}$/, 'Код валюти — три літери, наприклад USD');

/** Discount and tax are non-negative amounts; an empty field means zero. */
export const orderAmountSchema = z
  .string()
  .trim()
  .regex(AMOUNT_PATTERN, 'Сума — невідʼємне число, до двох знаків після коми')
  .optional()
  .or(z.literal(''));

export const orderNotesSchema = z.string().trim().max(4000, 'Не більше 4000 символів').optional();

export const orderQuantitySchema = z
  .number({ message: 'Вкажіть кількість' })
  .int('Кількість — ціле число')
  .min(1, 'Щонайменше 1')
  .max(1_000_000, 'Не більше 1 000 000');

/** Used by the search box of the list, where the API caps the term at 64. */
export const orderSearchSchema = z.string().trim().max(64, 'Не більше 64 символів');

/** Used by the total range in the filter row, where empty means «no bound». */
export const totalBoundSchema = z
  .string()
  .trim()
  .regex(AMOUNT_PATTERN, 'Невірна сума')
  .optional()
  .or(z.literal(''));

/** The fields of the order card itself; the lines are edited separately. */
export interface OrderFormValues {
  readonly ownerId?: string;
  readonly contactId?: string;
  readonly dealId?: string;
  readonly currency: string;
  readonly discountTotal?: string;
  readonly taxTotal?: string;
  readonly notes?: string;
}
