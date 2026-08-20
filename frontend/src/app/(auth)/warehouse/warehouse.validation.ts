import { z } from 'zod';
import type { StockOperation } from './warehouse.types';

/**
 * Mirrors the rules the API enforces, so an obviously wrong form never becomes
 * a request. The server validates independently — this only saves a round trip
 * and puts the message next to the field that caused it.
 */

const uuidField = z.uuid('Вкажіть коректний ідентифікатор');

const quantityField = z
  .number('Вкажіть кількість')
  .int('Кількість має бути цілим числом')
  .min(1, 'Кількість має бути більшою за нуль')
  .max(1_000_000_000, 'Завелика кількість');

const deltaField = z
  .number('Вкажіть коригування')
  .int('Коригування має бути цілим числом')
  .refine((value) => value !== 0, 'Коригування не може дорівнювати нулю');

const referenceTypeField = z
  .string()
  .trim()
  .min(1, 'Вкажіть тип підстави')
  .max(64, 'Не більше 64 символів');

const noteField = z.string().trim().min(1, 'Вкажіть коментар').max(255, 'Не більше 255 символів');

export const warehouseCodeSchema = z
  .string()
  .trim()
  .min(2, 'Не менше 2 символів')
  .max(32, 'Не більше 32 символів')
  .regex(/^[A-Za-z0-9][A-Za-z0-9_-]*$/, 'Дозволені літери, цифри, дефіс і підкреслення')
  .transform((value) => value.toUpperCase());

export const warehouseNameSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть назву')
  .max(120, 'Не більше 120 символів');

export const warehouseFormSchema = z.object({
  code: warehouseCodeSchema,
  name: warehouseNameSchema,
  isActive: z.boolean(),
});

export type WarehouseFormValues = z.infer<typeof warehouseFormSchema>;

const targetShape = { warehouseId: uuidField, productId: uuidField };

const receiveSchema = z.object({
  ...targetShape,
  quantity: quantityField,
  referenceType: referenceTypeField.optional(),
  referenceId: uuidField.optional(),
  note: noteField.optional(),
});

const issueSchema = z
  .object({
    ...targetShape,
    quantity: quantityField,
    fromReservation: z.boolean().optional(),
    referenceType: referenceTypeField.optional(),
    referenceId: uuidField.optional(),
    note: noteField.optional(),
  })
  .refine(
    (value) =>
      value.fromReservation !== true ||
      (value.referenceType !== undefined && value.referenceId !== undefined),
    { message: 'Списання з резерву має посилатися на резерв', path: ['referenceId'] },
  );

const reservationSchema = z.object({
  ...targetShape,
  quantity: quantityField,
  referenceType: referenceTypeField,
  referenceId: uuidField,
  note: noteField.optional(),
});

const adjustSchema = z.object({
  ...targetShape,
  delta: deltaField,
  // Deliberately required: a correction without a reason is not auditable.
  note: noteField,
  referenceType: referenceTypeField.optional(),
  referenceId: uuidField.optional(),
});

const OPERATION_SCHEMAS = {
  receive: receiveSchema,
  issue: issueSchema,
  reserve: reservationSchema,
  release: reservationSchema,
  adjust: adjustSchema,
} as const;

export const stockOperationSchema = (
  operation: StockOperation,
): (typeof OPERATION_SCHEMAS)[StockOperation] => OPERATION_SCHEMAS[operation];

/** Fields the modal shows for a given operation; everything else stays hidden. */
export const showsField = (
  operation: StockOperation,
  field: 'quantity' | 'delta' | 'fromReservation' | 'reference' | 'note',
): boolean => {
  switch (field) {
    case 'quantity':
      return operation !== 'adjust';
    case 'delta':
      return operation === 'adjust';
    case 'fromReservation':
      return operation === 'issue';
    default:
      return true;
  }
};

/** An empty input must be omitted from the body, not sent as an empty string. */
export const blankToUndefined = (value: string | undefined): string | undefined => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
};
