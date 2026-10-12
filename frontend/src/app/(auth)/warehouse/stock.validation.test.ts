import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/api';
import { formatMovementQuantity } from './movements/_hooks/movements.use-table-columns';
import { describeStockError } from './stock.queries';
import { ORDER_REFERENCE_MESSAGE, stockOperationSchema } from './warehouse.validation';

const TARGET = {
  warehouseId: '11111111-1111-4111-8111-111111111111',
  productId: '22222222-2222-4222-8222-222222222222',
};
const REFERENCE_ID = '33333333-3333-4333-8333-333333333333';

const messagesOf = (result: { success: boolean; error?: { issues: { message: string }[] } }) =>
  result.success ? [] : (result.error?.issues.map(({ message }) => message) ?? []);

describe('stock operations — an order reference', () => {
  // The order's own reservation moves only with the order's transitions; the
  // API refuses these three under its reference type.
  it.each(['reserve', 'release'] as const)('refuses %s under the order reference type', (op) => {
    const result = stockOperationSchema(op).safeParse({
      ...TARGET,
      quantity: 2,
      referenceType: 'order',
      referenceId: REFERENCE_ID,
    });

    expect(messagesOf(result)).toContain(ORDER_REFERENCE_MESSAGE);
  });

  it('refuses an issue under the order reference type', () => {
    const result = stockOperationSchema('issue').safeParse({
      ...TARGET,
      quantity: 2,
      fromReservation: true,
      referenceType: 'order',
      referenceId: REFERENCE_ID,
    });

    expect(messagesOf(result)).toContain(ORDER_REFERENCE_MESSAGE);
  });

  it('accepts the same operation under another reference type', () => {
    const result = stockOperationSchema('reserve').safeParse({
      ...TARGET,
      quantity: 2,
      referenceType: 'manual',
      referenceId: REFERENCE_ID,
    });

    expect(result.success).toBe(true);
  });

  // A receipt or an adjustment is not part of the order's reservation; the API
  // does not forbid them, and neither does the form.
  it('leaves a receipt under the order reference type alone', () => {
    const result = stockOperationSchema('receive').safeParse({
      ...TARGET,
      quantity: 2,
      referenceType: 'order',
      referenceId: REFERENCE_ID,
    });

    expect(result.success).toBe(true);
  });

  it('names the refusal when the API is the one to make it', () => {
    expect(
      describeStockError(
        new ApiError({ status: 409, code: 'STOCK_ORDER_REFERENCE_FORBIDDEN', message: '' }),
      ),
    ).toMatch(/Резервом замовлення керує саме замовлення/);
  });
});

describe('formatMovementQuantity', () => {
  // A write-off is a negative adjustment. Folded into an absolute value it would
  // read as stock that arrived.
  it('keeps the sign of an adjustment, both ways', () => {
    expect(formatMovementQuantity({ type: 'ADJUSTMENT', quantity: -5 })).toBe('−5');
    expect(formatMovementQuantity({ type: 'ADJUSTMENT', quantity: 3 })).toBe('+3');
  });

  it('prints every other movement as the amount its type already directs', () => {
    expect(formatMovementQuantity({ type: 'ISSUE', quantity: 4 })).toBe('4');
    expect(formatMovementQuantity({ type: 'RECEIPT', quantity: 10 })).toBe('10');
  });
});
