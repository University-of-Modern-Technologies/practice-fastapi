'use client';

import { Alert, Form, Select, Typography } from 'antd';
import { FormModal, ReferenceSelect } from '@/components';
import { ApiError } from '@/shared/api';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import { orderLabel, useOrderOptions, useResolvedOrder } from '../../orders/orders.queries';
import { useMatchTransaction } from '../finance.queries';
import { FINANCE_ERROR, type BankTransaction } from '../finance.types';

interface ManualMatchModalProps {
  /** The payment being tied; nothing is shown until the action is started. */
  readonly transaction: BankTransaction | null;
  readonly onCancel: () => void;
  readonly onMatched: () => void;
  /** A lost race is shown by the card, which owns the re-read. */
  readonly onConflict: (error: unknown) => boolean;
}

interface ManualMatchFormValues {
  readonly orderId?: string;
}

/**
 * Tying a payment to an order the rule did not put forward.
 *
 * It is a separate action from picking a candidate, and it has to stay separate
 * on screen: choosing between candidates is ratifying what the rule found,
 * while this is overruling it. The API treats both as the same call, which is
 * exactly why the interface must not — an operator who reaches for this one is
 * asserting something the evidence did not support, and should know it.
 */
export function ManualMatchModal({
  transaction,
  onCancel,
  onMatched,
  onConflict,
}: ManualMatchModalProps) {
  const [form] = Form.useForm<ManualMatchFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const match = useMatchTransaction(transaction?.id ?? '');

  // Reading orders is its own permission: without it the picker is not mounted
  // at all, so the dialog never fires a request the caller may not make.
  const canReadOrders = useHasPermission('orders', 'read');

  const submit = (): void => {
    if (transaction === null) return;

    void form
      .validateFields()
      .then((values) => {
        const orderId = values.orderId?.trim();
        if (!orderId) {
          form.setFields([{ name: 'orderId', errors: ['Виберіть замовлення'] }]);
          return;
        }

        match.mutate(
          // The version the card read: the payment is tied to the order by the
          // operator who was looking at this state of it.
          { version: transaction.version, orderId },
          {
            onSuccess: () => {
              reportSuccess('Платіж зведено із замовленням');
              onMatched();
            },
            onError: (error: unknown) => {
              if (onConflict(error)) {
                onCancel();
                return;
              }
              if (error instanceof ApiError) {
                // A refusal about the order belongs on the field that names it:
                // the operator has one picker to change.
                if (error.code === FINANCE_ERROR.orderNotFound) {
                  form.setFields([{ name: 'orderId', errors: ['Такого замовлення вже немає'] }]);
                  return;
                }
                if (error.code === FINANCE_ERROR.amountMismatch) {
                  form.setFields([
                    {
                      name: 'orderId',
                      errors: ['Сума платежу не збігається з підсумком цього замовлення'],
                    },
                  ]);
                  return;
                }
              }
              reportFailure(error);
            },
          },
        );
      })
      // A field that failed its own rule already shows why.
      .catch(() => undefined);
  };

  return (
    <FormModal
      open={transaction !== null}
      title="Звести платіж вручну"
      isSaving={match.isPending}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Звести"
      width={520}
    >
      {transaction === null ? null : (
        <>
          <Typography.Paragraph type="secondary">
            Платіж від «{transaction.counterpartyName}», призначення: {transaction.reference}.
            Оберіть замовлення, до якого він належить.
          </Typography.Paragraph>

          {canReadOrders ? null : (
            <Alert
              type="warning"
              showIcon
              className="mb-4"
              message="Немає доступу до замовлень"
              description="Звести платіж можна лише із замовленням, яке ви маєте право читати."
            />
          )}

          <Form<ManualMatchFormValues> form={form} layout="vertical" requiredMark={false}>
            <Form.Item
              name="orderId"
              label="Замовлення"
              extra={
                canReadOrders
                  ? 'Сервер перевірить суму й відмовить, якщо вона не збігається.'
                  : 'Немає доступу до замовлень'
              }
            >
              {canReadOrders ? (
                <ReferenceSelect
                  useOptions={useOrderOptions}
                  useResolved={useResolvedOrder}
                  getLabel={orderLabel}
                  placeholder="Оберіть замовлення"
                />
              ) : (
                <Select disabled placeholder="Оберіть замовлення" />
              )}
            </Form.Item>
          </Form>
        </>
      )}
    </FormModal>
  );
}
