import type { Dayjs } from 'dayjs';
import { z } from 'zod';

/**
 * Mirrors the rules the API enforces so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */

/** A comma is allowed on input because that is how the amount is typed here. */
const AMOUNT_PATTERN = /^\d{1,12}(?:[.,]\d{1,2})?$/;

export const dealTitleSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть назву угоди')
  .max(160, 'Не більше 160 символів');

export const dealAmountSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть суму')
  .regex(AMOUNT_PATTERN, 'Сума — невідʼємне число, до двох знаків після коми');

export const dealCurrencySchema = z
  .string()
  .trim()
  .regex(/^[A-Za-z]{3}$/, 'Код валюти — три літери, наприклад USD');

export const dealProbabilitySchema = z
  .number({ message: 'Вкажіть ймовірність' })
  .int('Ймовірність — ціле число')
  .min(0, 'Не менше 0')
  .max(100, 'Не більше 100');

/** Used by the amount range in the filter row, where empty means «no bound». */
export const amountBoundSchema = z
  .string()
  .trim()
  .regex(AMOUNT_PATTERN, 'Невірна сума')
  .optional()
  .or(z.literal(''));

/**
 * The value a non-terminal stage may not carry. Only a won deal is certain, so
 * the field refuses 100 everywhere else — the API answers 400
 * `INVALID_DEAL_PROBABILITY` for the same value.
 */
export const CERTAIN_PROBABILITY = 100;

/** What the form holds while it is being filled in. */
export interface DealFormValues {
  readonly title: string;
  readonly contactId?: string | undefined;
  readonly amount: string;
  readonly currency: string;
  readonly probability: number;
  readonly expectedCloseDate?: Dayjs | null | undefined;
}

/** What the transition dialog holds: the target stage is fixed by the button. */
export interface DealTransitionFormValues {
  readonly probability: number;
}
