'use client';

import { Button, Card, Form } from 'antd';
import { Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { FormCard, PageHeader, PermissionGate } from '@/components';
import type { Product } from '@/app/(auth)/products/products.types';
import { DEFAULT_CURRENCY, Money } from '@/lib/money';
import { AddItemModal, OrderItemsTable, OrderTotals } from '../_components';
import { useOrderForm } from '../_hooks';
import type { CreateOrderItemInput, OrderItemView } from '../orders.types';
import type { OrderFormValues } from '../orders.validation';

interface StagedItem {
  readonly product: Product;
  readonly quantity: number;
}

/** A malformed amount still being typed must not blow up the preview. */
const toMoney = (value: string | undefined, currency: string): Money => {
  if (value === undefined || value.trim() === '') return Money.zero(currency);
  try {
    return Money.fromInput(value, currency);
  } catch {
    return Money.zero(currency);
  }
};

export default function NewOrderPage() {
  const router = useRouter();
  const [staged, setStaged] = useState<readonly StagedItem[]>([]);
  const [isAdding, setIsAdding] = useState(false);

  const items = useMemo<readonly CreateOrderItemInput[]>(
    () => staged.map(({ product, quantity }) => ({ productId: product.id, quantity })),
    [staged],
  );

  const { formProps, fields, conflictAlert, submit, isSaving } = useOrderForm({
    items,
    onSaved: (order) => router.replace(`/orders/${order.id}`),
  });

  const { form } = formProps;
  const currency = (Form.useWatch('currency', form) ?? DEFAULT_CURRENCY).trim().toUpperCase();
  const discount = toMoney(Form.useWatch('discountTotal', form), currency);
  const tax = toMoney(Form.useWatch('taxTotal', form), currency);

  // A preview, not a result: the order does not exist yet, so there is no
  // server-side total to render. Once it is created the card shows the numbers
  // the API derived, and this arithmetic is never sent anywhere.
  const views: readonly OrderItemView[] = staged.map(({ product, quantity }) => ({
    id: product.id,
    productId: product.id,
    sku: product.sku,
    name: product.name,
    quantity,
    unitPrice: Money.parse(product.unitPrice, currency).toWire(),
    lineTotal: Money.parse(product.unitPrice, currency).times(quantity).toWire(),
  }));

  const subtotal =
    views.length === 0
      ? Money.zero(currency)
      : Money.sum(views.map((view) => Money.parse(view.lineTotal, currency)));
  const total = subtotal.minus(discount).plus(tax);

  const addButton = (
    <Button icon={<Plus size={16} />} onClick={() => setIsAdding(true)}>
      Додати позицію
    </Button>
  );

  return (
    <PermissionGate resource="orders" action="write">
      <PageHeader
        title="Нове замовлення"
        description="Номер, статус і суми замовлення визначає сервер після створення"
      />

      {conflictAlert}

      <Form<OrderFormValues> {...formProps}>
        <FormCard
          title="Дані замовлення"
          isSaving={isSaving}
          onSubmit={submit}
          submitLabel="Створити"
          backHref="/orders"
        >
          {fields}
        </FormCard>
      </Form>

      <Card className="mt-4" title="Позиції" extra={addButton}>
        <OrderItemsTable
          items={views}
          currency={currency}
          isEditable
          onQuantityChange={(item, quantity) =>
            setStaged((current) =>
              current.map((entry) =>
                entry.product.id === item.productId ? { ...entry, quantity } : entry,
              ),
            )
          }
          onRemove={(item) =>
            setStaged((current) => current.filter((entry) => entry.product.id !== item.productId))
          }
          emptyAction={addButton}
        />

        <div className="mt-4">
          <OrderTotals
            isPreview
            subtotal={subtotal.toWire()}
            discountTotal={discount.toWire()}
            taxTotal={tax.toWire()}
            total={total.toWire()}
            currency={currency}
          />
        </div>
      </Card>

      <AddItemModal
        open={isAdding}
        onClose={() => setIsAdding(false)}
        currency={currency}
        onStage={(item) =>
          setStaged((current) =>
            // The API refuses a product twice on one order, so the staged list
            // holds the same rule: a repeated pick replaces the quantity.
            current.some((entry) => entry.product.id === item.product.id)
              ? current.map((entry) =>
                  entry.product.id === item.product.id
                    ? { ...entry, quantity: item.quantity }
                    : entry,
                )
              : [...current, item],
          )
        }
      />
    </PermissionGate>
  );
}
