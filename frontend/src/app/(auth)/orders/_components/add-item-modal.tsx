'use client';

import { Alert, Form, InputNumber, Space } from 'antd';
import { useState } from 'react';
import { FormModal, MoneyValue, ReferenceSelect, applyServerErrors, zodRule } from '@/components';
import {
  productLabel,
  useProductOptions,
  useResolvedProduct,
} from '@/app/(auth)/products/products.queries';
import type { Product } from '@/app/(auth)/products/products.types';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import type { CurrencyCode, Id } from '@/types/domain';
import { useAddOrderItem } from '../orders.queries';
import { ORDER_ERROR, ORDER_ERROR_MESSAGES, type Order } from '../orders.types';
import { orderProductSchema, orderQuantitySchema } from '../orders.validation';

interface ItemFormValues {
  productId: Id;
  quantity: number;
}

interface AddItemModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly currency: CurrencyCode;
  /** Present once the order exists: the line is written through the API. */
  readonly order?: Order | undefined;
  /** Present on the create route: the line is staged until the order exists. */
  readonly onStage?: ((item: { product: Product; quantity: number }) => void) | undefined;
  /** Lets the card show the conflict alert; returns true when it took over. */
  readonly onConflict?: ((error: unknown) => boolean) | undefined;
}

/**
 * Picks a catalogue position and a quantity. The catalogue is read straight
 * from the products module rather than mirrored here: the search endpoint is
 * the same one that page uses, so there is exactly one way to look a product up.
 */
export function AddItemModal({
  open,
  onClose,
  currency,
  order,
  onStage,
  onConflict,
}: AddItemModalProps) {
  const [form] = Form.useForm<ItemFormValues>();
  const [selected, setSelected] = useState<Product | undefined>(undefined);
  const { reportFailureWith } = useMutationFeedback();
  const addItem = useAddOrderItem(order?.id ?? '');

  const reset = (): void => {
    form.resetFields();
    setSelected(undefined);
  };

  const close = (): void => {
    reset();
    onClose();
  };

  const handleError = (error: unknown): void => {
    if (onConflict?.(error) === true) {
      close();
      return;
    }

    // A duplicate names the field that caused it: the user has to pick another
    // product or go and change the quantity of the line that already exists.
    if (error instanceof ApiError && error.code === ORDER_ERROR.itemDuplicate) {
      form.setFields([
        { name: 'productId', errors: [ORDER_ERROR_MESSAGES[ORDER_ERROR.itemDuplicate] ?? ''] },
      ]);
      return;
    }

    if (applyServerErrors(form, error)) return;
    reportFailureWith(ORDER_ERROR_MESSAGES)(error);
  };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        if (order === undefined) {
          if (selected === undefined) return;
          onStage?.({ product: selected, quantity: values.quantity });
          close();
          return;
        }

        addItem.mutate(
          // The version read with the card; a stale one answers 409.
          { version: order.version, productId: values.productId, quantity: values.quantity },
          { onSuccess: close, onError: handleError },
        );
      })
      .catch(() => undefined);
  };

  const mismatched = selected !== undefined && selected.currency !== currency;

  return (
    <FormModal
      open={open}
      title="Додати позицію"
      submitLabel="Додати"
      isSaving={addItem.isPending}
      onSubmit={submit}
      onCancel={close}
    >
      <Form<ItemFormValues> form={form} layout="vertical" initialValues={{ quantity: 1 }}>
        <Form.Item name="productId" label="Товар" rules={[zodRule(orderProductSchema)]}>
          <ReferenceSelect
            useOptions={useProductOptions}
            useResolved={useResolvedProduct}
            getLabel={productLabel}
            placeholder="Почніть вводити назву або артикул"
            notFoundText="Товарів не знайдено"
            onSelectRow={setSelected}
          />
        </Form.Item>

        {selected ? (
          <Space size="small" className="mb-4">
            <span>Ціна:</span>
            <MoneyValue value={selected.unitPrice} currency={selected.currency} showCurrency />
          </Space>
        ) : null}

        {mismatched ? (
          <Alert
            className="mb-4"
            type="warning"
            showIcon
            message={`Валюта товару (${selected?.currency}) не збігається з валютою замовлення (${currency})`}
          />
        ) : null}

        <Form.Item name="quantity" label="Кількість" rules={[zodRule(orderQuantitySchema)]}>
          <InputNumber min={1} max={1_000_000} step={1} precision={0} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </FormModal>
  );
}
