import { z } from 'zod';

/**
 * Mirrors the rules the API enforces so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */

/** Matches the catalogue identifier the API accepts; it is stored upper-cased. */
const SKU_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

/** A comma is allowed on input because that is how the amount is typed here. */
const AMOUNT_PATTERN = /^\d{1,12}(?:[.,]\d{1,2})?$/;

export const productSkuSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть артикул')
  .max(64, 'Не більше 64 символів')
  .regex(SKU_PATTERN, 'Дозволені літери, цифри та символи . _ -');

export const productNameSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть назву')
  .max(160, 'Не більше 160 символів');

export const productDescriptionSchema = z
  .string()
  .trim()
  .max(4000, 'Не більше 4000 символів')
  .optional();

export const productCategorySchema = z.string().trim().max(80, 'Не більше 80 символів').optional();

export const productPriceSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть ціну')
  .regex(AMOUNT_PATTERN, 'Ціна — невідʼємне число, до двох знаків після коми');

export const productCurrencySchema = z
  .string()
  .trim()
  .regex(/^[A-Za-z]{3}$/, 'Код валюти — три літери, наприклад USD');

/** Used by the price range in the filter row, where an empty value means «no bound». */
export const priceBoundSchema = z
  .string()
  .trim()
  .regex(AMOUNT_PATTERN, 'Невірна сума')
  .optional()
  .or(z.literal(''));

export interface ProductFormValues {
  readonly sku: string;
  readonly name: string;
  readonly description?: string;
  readonly category?: string;
  readonly unitPrice: string;
  readonly currency: string;
  readonly isActive: boolean;
}
