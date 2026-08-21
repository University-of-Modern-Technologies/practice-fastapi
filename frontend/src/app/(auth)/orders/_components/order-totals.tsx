'use client';

import { Descriptions } from 'antd';
import { MoneyValue } from '@/components';
import type { CurrencyCode, MoneyWire } from '@/types/domain';

interface OrderTotalsProps {
  /** All four amounts come from the server; the client never recomputes them. */
  readonly subtotal: MoneyWire;
  readonly discountTotal: MoneyWire;
  readonly taxTotal: MoneyWire;
  readonly total: MoneyWire;
  readonly currency: CurrencyCode;
  /**
   * Set on the create route, where the order does not exist yet and the numbers
   * are a preview of what the server will derive from the staged lines.
   */
  readonly isPreview?: boolean;
}

/**
 * The money block of an order. Rendering the server's own numbers is the point:
 * a client-side recalculation would eventually disagree with the record, and
 * the record is what gets paid.
 */
export function OrderTotals({
  subtotal,
  discountTotal,
  taxTotal,
  total,
  currency,
  isPreview = false,
}: OrderTotalsProps) {
  return (
    <Descriptions
      size="small"
      column={{ xs: 1, sm: 2, lg: 4 }}
      bordered
      title={isPreview ? 'Попередній підрахунок' : 'Суми замовлення'}
      extra={
        isPreview ? (
          <span className="text-xs opacity-70">Остаточні суми порахує сервер після створення</span>
        ) : null
      }
    >
      <Descriptions.Item label="Проміжна сума">
        <MoneyValue value={subtotal} currency={currency} showCurrency />
      </Descriptions.Item>
      <Descriptions.Item label="Знижка">
        <MoneyValue value={discountTotal} currency={currency} showCurrency />
      </Descriptions.Item>
      <Descriptions.Item label="Податок">
        <MoneyValue value={taxTotal} currency={currency} showCurrency />
      </Descriptions.Item>
      <Descriptions.Item label="Разом">
        <strong>
          <MoneyValue value={total} currency={currency} showCurrency />
        </strong>
      </Descriptions.Item>
    </Descriptions>
  );
}
