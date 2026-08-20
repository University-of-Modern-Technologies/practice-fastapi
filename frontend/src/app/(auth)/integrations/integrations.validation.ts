import { z } from 'zod';
import type { DeliveryQuote } from './integrations.types';

/**
 * Mirrors the bounds the API enforces, so a request that would come back as a
 * 400 never leaves the browser. The server validates independently — this only
 * saves the operator a round trip and names the offending field.
 */

export const PARCEL_LIMITS = {
  weightGrams: { min: 1, max: 1_000_000 },
  dimensionCm: { min: 1, max: 500 },
} as const;

const AMOUNT_PATTERN = /^\d{1,12}(?:[.,]\d{1,2})?$/;

export const orderIdSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть номер замовлення')
  .max(64, 'Не більше 64 символів');

export const quoteIdSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть ідентифікатор розрахунку')
  .max(128, 'Не більше 128 символів');

export const shipmentIdSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть номер відправлення')
  .max(128, 'Не більше 128 символів');

export const referenceSchema = z.string().trim().max(120, 'Не більше 120 символів').optional();

export const countrySchema = z
  .string()
  .trim()
  .regex(/^[A-Za-z]{2}$/, 'Код країни — дві літери, наприклад UA');

export const citySchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть місто')
  .max(120, 'Не більше 120 символів');

export const postalCodeSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть поштовий індекс')
  .max(20, 'Не більше 20 символів');

export const line1Schema = z
  .string()
  .trim()
  .min(1, 'Вкажіть адресу')
  .max(200, 'Не більше 200 символів');

/** A comma is allowed on input because that is how an amount is typed here. */
export const declaredValueSchema = z
  .string()
  .trim()
  .regex(AMOUNT_PATTERN, 'Сума — невідʼємне число, до двох знаків після коми')
  .optional()
  .or(z.literal(''));

/**
 * The country code is stored upper-cased, and the field shows what will be
 * sent: typing `ua` and reading `ua` back while the API records `UA` invites a
 * bug report about a value nobody actually changed.
 */
export const normalizeCountry = (value: string): string =>
  value
    .replace(/[^A-Za-z]/g, '')
    .toUpperCase()
    .slice(0, 2);

export interface AddressFormValues {
  readonly country: string;
  readonly city: string;
  readonly postalCode: string;
  readonly line1: string;
}

export interface ParcelFormValues {
  readonly weightGrams: number;
  readonly lengthCm: number;
  readonly widthCm: number;
  readonly heightCm: number;
}

export interface QuoteFormValues {
  readonly orderId: string;
  readonly origin: AddressFormValues;
  readonly destination: AddressFormValues;
  readonly parcel: ParcelFormValues;
  readonly declaredValue?: string;
}

export interface ShipmentFormValues {
  readonly quoteId: string;
  readonly orderId: string;
  readonly destination: AddressFormValues;
  readonly parcel: ParcelFormValues;
  readonly reference?: string;
}

/**
 * A quote is a price with a deadline. Creating a shipment against an expired
 * one is refused upstream, so the client says so while the operator is still
 * looking at the card rather than after the failed write.
 */
export const isQuoteExpired = (quote: DeliveryQuote, now: number = Date.now()): boolean => {
  const expiresAt = Date.parse(quote.expiresAt);
  if (Number.isNaN(expiresAt)) return false;
  return expiresAt <= now;
};

/** Sensible starting point: a small parcel, so the form opens usable. */
export const DEFAULT_PARCEL: ParcelFormValues = {
  weightGrams: 1000,
  lengthCm: 20,
  widthCm: 15,
  heightCm: 10,
};
