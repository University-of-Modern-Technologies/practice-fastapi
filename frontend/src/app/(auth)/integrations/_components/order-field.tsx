'use client';

import { Form, Select } from 'antd';
import { ReferenceSelect, zodRule } from '@/components';
import { useResolvedOrder } from '@/app/(auth)/orders/orders.queries';
import { shippableOrderLabel, useShippableOrderOptions } from '../integrations.queries';
import { orderIdSchema } from '../integrations.validation';

interface ShippableOrderFieldProps {
  /** Whether the role may read orders; without it there is nothing to pick from. */
  readonly canReadOrders: boolean;
}

/**
 * The order a parcel is for, picked from the confirmed and paid ones. Both
 * delivery forms carry it, under the same rule: the API ships only an order it
 * can find and that is ready to leave, so a typed identifier is not offered.
 *
 * A role without access to orders gets a disabled field and the reason. The
 * API checks the order under the caller's own access, so such a role could not
 * quote or ship anything even with an identifier copied from elsewhere.
 */
export function ShippableOrderField({ canReadOrders }: ShippableOrderFieldProps) {
  return (
    <Form.Item
      name="orderId"
      label="Замовлення"
      rules={[zodRule(orderIdSchema)]}
      extra={
        canReadOrders
          ? 'Лише підтверджені або оплачені замовлення'
          : 'Ваша роль не дає доступу до замовлень, тому доставку оформити не можна'
      }
    >
      {canReadOrders ? (
        <ReferenceSelect
          useOptions={useShippableOrderOptions}
          useResolved={useResolvedOrder}
          getLabel={shippableOrderLabel}
          placeholder="Почніть вводити номер замовлення"
          notFoundText="Немає підтверджених або оплачених замовлень"
          allowClear={false}
        />
      ) : (
        <Select disabled placeholder="Немає доступу до замовлень" />
      )}
    </Form.Item>
  );
}
