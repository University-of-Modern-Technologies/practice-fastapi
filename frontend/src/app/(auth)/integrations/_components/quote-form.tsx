'use client';

import { Alert, Button, Card, Divider, Form, Input, Space } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import {
  CopyableValue,
  DateValue,
  DetailsCard,
  DetailsItem,
  FormCard,
  MoneyValue,
  applyServerErrors,
  zodRule,
} from '@/components';
import { formatCount } from '@/lib/number';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import { useCreateQuote } from '../integrations.queries';
import {
  describeShipmentOrderError,
  isModuleUnavailable,
  toQuoteRequest,
} from '../integrations.service';
import { DELIVERY_ERROR_MESSAGES, type QuoteResult } from '../integrations.types';
import {
  DEFAULT_PARCEL,
  declaredValueSchema,
  isQuoteExpired,
  type QuoteFormValues,
} from '../integrations.validation';
import { AddressFields, ParcelFields } from './address-fields';
import { ShippableOrderField } from './order-field';

interface QuoteFormProps {
  /** Hands the fresh quote to the shipment form, which is created against it. */
  readonly onQuoted: (result: QuoteResult) => void;
  /** Raised when the answer says the whole section is absent from this API build. */
  readonly onUnavailable: () => void;
}

/** How often the card re-checks the deadline it is showing. */
const EXPIRY_TICK_MS = 30_000;

const INITIAL_VALUES: Partial<QuoteFormValues> = { parcel: DEFAULT_PARCEL };

export function QuoteForm({ onQuoted, onUnavailable }: QuoteFormProps) {
  const [form] = Form.useForm<QuoteFormValues>();
  const [result, setResult] = useState<QuoteResult | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const createQuote = useCreateQuote();

  // The picker reads the orders list, which is a permission of its own — and
  // the API checks the order under the same permission, so without it there is
  // nothing this form could quote.
  const canReadOrders = useHasPermission('orders', 'read');

  const reportFailure = reportFailureWith(DELIVERY_ERROR_MESSAGES);

  // A quote that was valid when it arrived stops being valid while it is on
  // screen; without this the card would keep claiming a price nobody can use.
  useEffect(() => {
    if (!result) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), EXPIRY_TICK_MS);
    return () => window.clearInterval(timer);
  }, [result]);

  const submit = useCallback(() => {
    if (!canReadOrders) return;
    void form
      .validateFields()
      .then((values) => {
        const request = toQuoteRequest(values);

        createQuote.mutate(request, {
          onSuccess: (quote) => {
            const quoted: QuoteResult = { quote, request };
            setResult(quoted);
            setNow(Date.now());
            reportSuccess('Розрахунок отримано');
            onQuoted(quoted);
          },
          onError: (error) => {
            if (isModuleUnavailable(error)) {
              onUnavailable();
              return;
            }
            const orderError = describeShipmentOrderError(error);
            if (orderError !== null) {
              form.setFields([{ name: 'orderId', errors: [orderError] }]);
              return;
            }
            if (applyServerErrors(form, error)) return;
            reportFailure(error);
          },
        });
      })
      // A form that failed its own rules has already marked the fields.
      .catch(() => undefined);
  }, [canReadOrders, createQuote, form, onQuoted, onUnavailable, reportFailure, reportSuccess]);

  const expired = result !== null && isQuoteExpired(result.quote, now);

  return (
    <FormCard
      title="Розрахунок доставки"
      isSaving={createQuote.isPending}
      {...(canReadOrders ? { onSubmit: submit } : {})}
      submitLabel="Розрахувати"
    >
      <Form<QuoteFormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={INITIAL_VALUES}
        onFinish={submit}
      >
        <ShippableOrderField canReadOrders={canReadOrders} />

        <AddressFields name="origin" legend="Звідки" hint="Склад або точка відправлення" />
        <Divider />
        <AddressFields name="destination" legend="Куди" hint="Адреса отримувача" />
        <Divider />
        <ParcelFields name="parcel" />

        <Form.Item
          name="declaredValue"
          label="Оголошена вартість"
          rules={[zodRule(declaredValueSchema)]}
          extra="Необовʼязково. Впливає на страхування відправлення."
        >
          <Input className="numeric" inputMode="decimal" placeholder="1200.00" />
        </Form.Item>
      </Form>

      {result ? (
        <Card size="small" className="mt-4" title="Результат розрахунку">
          <Space direction="vertical" size="middle" className="w-full">
            {expired ? (
              <Alert
                type="warning"
                showIcon
                message="Термін дії розрахунку минув"
                description="Ціну більше не гарантовано — виконайте розрахунок ще раз, перш ніж створювати відправлення."
              />
            ) : null}

            <DetailsCard>
              <DetailsItem label="Перевізник">{result.quote.carrier}</DetailsItem>
              <DetailsItem label="Послуга">{result.quote.service}</DetailsItem>
              <DetailsItem label="Вартість">
                <MoneyValue
                  value={result.quote.amount}
                  currency={result.quote.currency}
                  showCurrency
                />
              </DetailsItem>
              <DetailsItem label="Орієнтовний строк">
                <span className="numeric">{formatCount(result.quote.estimatedDays)}</span> дн.
              </DetailsItem>
              <DetailsItem label="Дійсний до">
                <DateValue value={result.quote.expiresAt} withTime />
              </DetailsItem>
              <DetailsItem label="Ідентифікатор">
                <CopyableValue value={result.quote.quoteId} />
              </DetailsItem>
            </DetailsCard>

            <Button onClick={() => onQuoted(result)} disabled={expired}>
              Підставити у форму відправлення
            </Button>
          </Space>
        </Card>
      ) : null}
    </FormCard>
  );
}
