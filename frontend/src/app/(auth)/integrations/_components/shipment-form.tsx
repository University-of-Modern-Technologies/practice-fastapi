'use client';

import { Alert, Card, Divider, Form, Input, Space } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import {
  FormCard,
  PermissionGate,
  ReferenceSelect,
  applyServerErrors,
  zodRule,
} from '@/components';
import { orderLabel, useOrderOptions, useResolvedOrder } from '@/app/(auth)/orders/orders.queries';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import { useCreateShipment } from '../integrations.queries';
import { isModuleUnavailable, toShipmentInput } from '../integrations.service';
import { DELIVERY_ERROR_MESSAGES, type QuoteResult, type Shipment } from '../integrations.types';
import {
  DEFAULT_PARCEL,
  orderIdSchema,
  quoteIdSchema,
  referenceSchema,
  type ShipmentFormValues,
} from '../integrations.validation';
import { AddressFields, ParcelFields } from './address-fields';
import { ShipmentDetails } from './shipment-lookup';

interface ShipmentFormProps {
  /** The latest quote, if there is one: the shipment is created against it. */
  readonly quote: QuoteResult | null;
  readonly onUnavailable: () => void;
}

const INITIAL_VALUES: Partial<ShipmentFormValues> = { parcel: DEFAULT_PARCEL };

export function ShipmentForm({ quote, onUnavailable }: ShipmentFormProps) {
  const [form] = Form.useForm<ShipmentFormValues>();
  const [created, setCreated] = useState<Shipment | null>(null);
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const createShipment = useCreateShipment();

  // The picker reads the orders list, which is a permission of its own: without
  // it the identifier is typed by hand rather than requested and refused.
  const canReadOrders = useHasPermission('orders', 'read');

  const reportFailure = reportFailureWith(DELIVERY_ERROR_MESSAGES);

  // The carrier prices a specific parcel to a specific address; retyping those
  // three blocks by hand is how a shipment ends up not matching its own quote.
  useEffect(() => {
    if (!quote) return;
    form.setFieldsValue({
      quoteId: quote.quote.quoteId,
      orderId: quote.request.orderId,
      destination: quote.request.destination,
      parcel: quote.request.parcel,
    });
  }, [form, quote]);

  const submit = useCallback(() => {
    void form
      .validateFields()
      .then((values) => {
        createShipment.mutate(toShipmentInput(values), {
          onSuccess: (shipment) => {
            setCreated(shipment);
            reportSuccess('Відправлення створено');
          },
          onError: (error) => {
            if (isModuleUnavailable(error)) {
              onUnavailable();
              return;
            }
            if (applyServerErrors(form, error)) return;
            reportFailure(error);
          },
        });
      })
      .catch(() => undefined);
  }, [createShipment, form, onUnavailable, reportFailure, reportSuccess]);

  return (
    <PermissionGate
      resource="integrations"
      action="write"
      fallback={
        <Card size="small" title="Створення відправлення">
          <Alert
            type="info"
            showIcon
            message="Ваша роль дозволяє лише переглядати інтеграцію"
            description="Створення відправлень доступне користувачам із дозволом на запис."
          />
        </Card>
      }
    >
      <FormCard
        title="Створення відправлення"
        isSaving={createShipment.isPending}
        onSubmit={submit}
        submitLabel="Створити"
      >
        <Form<ShipmentFormValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={INITIAL_VALUES}
          onFinish={submit}
        >
          {/* The carrier issues a quote and never lists them back, so there is
              no directory to pick from: the identifier arrives from the card on
              the left or is copied in by hand. */}
          <Form.Item
            name="quoteId"
            label="Розрахунок"
            rules={[zodRule(quoteIdSchema)]}
            extra="Підставляється з результату розрахунку зліва"
          >
            <Input placeholder="Ідентифікатор розрахунку" maxLength={128} />
          </Form.Item>

          <Form.Item
            name="orderId"
            label="Замовлення"
            rules={[zodRule(orderIdSchema)]}
            extra={canReadOrders ? undefined : 'Ваша роль не дає доступу до списку замовлень'}
          >
            {canReadOrders ? (
              <ReferenceSelect
                useOptions={useOrderOptions}
                useResolved={useResolvedOrder}
                getLabel={orderLabel}
                placeholder="Почніть вводити номер замовлення"
                notFoundText="Замовлень не знайдено"
                allowClear={false}
              />
            ) : (
              <Input placeholder="Ідентифікатор замовлення" maxLength={64} />
            )}
          </Form.Item>

          <AddressFields name="destination" legend="Куди" hint="Адреса отримувача" />
          <Divider />
          <ParcelFields name="parcel" />

          <Form.Item
            name="reference"
            label="Внутрішня примітка"
            rules={[zodRule(referenceSchema)]}
            extra="Необовʼязково. Видно у службі доставки."
          >
            <Input placeholder="Наприклад, номер накладної" maxLength={120} />
          </Form.Item>
        </Form>

        {created ? (
          <Space direction="vertical" size="middle" className="mt-4 w-full">
            <Alert type="success" showIcon message="Відправлення передано службі доставки" />
            <ShipmentDetails shipment={created} />
          </Space>
        ) : null}
      </FormCard>
    </PermissionGate>
  );
}
