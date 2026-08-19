import { z } from 'zod';
import { SETTING_KEYS, type SettingKey } from './settings.types';

/**
 * Which control a key gets in the editor. The registry declares a concrete type
 * per key, so a currency code is entered as a currency code — a single JSON box
 * for everything would push a server-side rejection onto the user for a mistake
 * the form could have caught.
 */
export type SettingFieldKind = 'text' | 'currency' | 'code' | 'json';

export interface SettingFieldSpec {
  readonly kind: SettingFieldKind;
  /** Validates what the user typed, i.e. the raw form value, always a string. */
  readonly schema: z.ZodType;
  readonly label: string;
  readonly hint: string;
  /** Mirrors the server-side bound; `null` where the value is not a short string. */
  readonly maxLength: number | null;
  /** What the value falls back to once the key is reset. */
  readonly defaultValue: string;
}

const currencyCode = z
  .string()
  .trim()
  .regex(/^[A-Za-z]{3}$/, 'Код валюти — три латинські літери, наприклад USD');

const shortCode = (max: number): z.ZodType =>
  z
    .string()
    .trim()
    .regex(
      /^[A-Za-z0-9][A-Za-z0-9_-]*$/,
      'Дозволені латинські літери, цифри, «-» і «_»; перший символ — літера або цифра',
    )
    .max(max, `Не більше ${max} символів`);

/** Fallback for a key the client does not know: valid JSON is the only rule. */
const jsonText = z
  .string()
  .trim()
  .min(1, 'Обовʼязкове поле')
  .refine((value) => {
    try {
      JSON.parse(value);
      return true;
    } catch {
      return false;
    }
  }, 'Значення має бути коректним JSON');

const JSON_FIELD: SettingFieldSpec = {
  kind: 'json',
  schema: jsonText,
  label: 'Значення',
  hint: 'Ключ невідомий цій версії клієнта — вкажіть значення як JSON.',
  maxLength: null,
  defaultValue: '',
};

export const SETTING_FIELDS: Readonly<Record<SettingKey, SettingFieldSpec>> = {
  'organization.name': {
    kind: 'text',
    schema: z.string().trim().min(1, 'Обовʼязкове поле').max(120, 'Не більше 120 символів'),
    label: 'Назва організації',
    hint: 'Показується в заголовках і документах.',
    maxLength: 120,
    defaultValue: 'Training CRM',
  },
  'organization.defaultCurrency': {
    kind: 'currency',
    schema: currencyCode,
    label: 'Валюта за замовчуванням',
    hint: 'Застосовується до нових угод і замовлень. Код ISO 4217, наприклад USD.',
    maxLength: 3,
    defaultValue: 'USD',
  },
  'orders.numberPrefix': {
    kind: 'code',
    schema: shortCode(8),
    label: 'Префікс номера замовлення',
    hint: 'Підставляється перед згенерованим номером, наприклад ORD-000123.',
    maxLength: 8,
    defaultValue: 'ORD',
  },
  'warehouse.defaultCode': {
    kind: 'code',
    schema: shortCode(32),
    label: 'Склад за замовчуванням',
    hint: 'Використовується, коли запит не називає склад явно.',
    maxLength: 32,
    defaultValue: 'CENTRAL',
  },
};

export const isKnownSettingKey = (key: string): key is SettingKey =>
  (SETTING_KEYS as readonly string[]).includes(key);

export const settingField = (key: string): SettingFieldSpec =>
  isKnownSettingKey(key) ? SETTING_FIELDS[key] : JSON_FIELD;

export const settingLabel = (key: string): string =>
  isKnownSettingKey(key) ? SETTING_FIELDS[key].label : key;

/** Stored value → the text shown in the editor. */
export const toFormValue = (key: string, value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (settingField(key).kind === 'json') return JSON.stringify(value, null, 2);
  return typeof value === 'string' ? value : JSON.stringify(value);
};

/** Editor text → the value sent to the API, in the shape the key declares. */
export const toWireValue = (key: string, input: string): unknown => {
  const field = settingField(key);
  if (field.kind === 'json') return JSON.parse(input) as unknown;
  // Codes are stored upper-cased by the API; doing it here keeps what the user
  // sees after saving identical to what they typed.
  const trimmed = input.trim();
  return field.kind === 'text' ? trimmed : trimmed.toUpperCase();
};

/** How a value reads in the table — a JSON payload never spans several lines. */
export const toDisplayValue = (value: unknown): string => {
  if (value === null || value === undefined) return '—';
  return typeof value === 'string' ? value : JSON.stringify(value);
};

export const descriptionSchema = z.string().trim().max(255, 'Не більше 255 символів').optional();
