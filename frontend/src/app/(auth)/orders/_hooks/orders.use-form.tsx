'use client';

import { Col, Form, Input, Row, Select, type FormInstance } from 'antd';
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { ConflictAlert, ReferenceSelect, applyServerErrors, zodRule } from '@/components';
import {
  contactLabel,
  useContactOptions,
  useResolvedContact,
} from '@/app/(auth)/contacts/contacts.queries';
import { dealLabel, useDealOptions, useResolvedDeal } from '@/app/(auth)/deals/deals.queries';
import { useResolvedUser, useUserOptions, userLabel } from '@/app/(auth)/users/users.queries';
import { DEFAULT_CURRENCY, Money } from '@/lib/money';
import { isOrderEditable } from '@/shared/constants';
import {
  useHasPermission,
  useMutationFeedback,
  useUnsavedChanges,
  useVersionConflict,
} from '@/shared/hooks';
import { useCreateOrder, useUpdateOrder } from '../orders.queries';
import {
  ORDER_ERROR_MESSAGES,
  isOrderVersionConflict,
  type CreateOrderInput,
  type CreateOrderItemInput,
  type Order,
  type UpdateOrderInput,
} from '../orders.types';
import {
  orderAmountSchema,
  orderCurrencySchema,
  orderNotesSchema,
  orderReferenceSchema,
  type OrderFormValues,
} from '../orders.validation';

interface UseOrderFormOptions {
  /** Absent on the create route; present, and the form edits that record. */
  readonly order?: Order | undefined;
  /** Lines staged on the create route; ignored once the order exists. */
  readonly items?: readonly CreateOrderItemInput[] | undefined;
  readonly onSaved: (order: Order) => void;
  /** Re-reads the record after a lost race, so the next save carries the current version. */
  readonly onReload?: (() => unknown) | undefined;
  readonly isReloading?: boolean | undefined;
}

interface UseOrderFormResult {
  readonly formProps: {
    readonly form: FormInstance<OrderFormValues>;
    readonly initialValues: Partial<OrderFormValues>;
    readonly layout: 'vertical';
    readonly requiredMark: boolean;
    readonly onValuesChange: () => void;
    readonly onFinish: () => void;
  };
  readonly fields: ReactNode;
  readonly conflictAlert: ReactNode;
  readonly submit: () => void;
  readonly isSaving: boolean;
  /** False for a fulfilled or cancelled order: the card is then read-only. */
  readonly canSubmit: boolean;
  /** Routes a failed write to the field it belongs to; also used by the delete action. */
  readonly handleError: (error: unknown) => void;
}

const asText = (value: string | undefined): string => (value ?? '').trim();

/** An empty amount means «unchanged zero», not a request to send an empty string. */
const toAmount = (value: string | undefined, currency: string): string | undefined => {
  const trimmed = asText(value);
  return trimmed === '' ? undefined : Money.fromInput(trimmed, currency).toWire();
};

/** Shown instead of a picker the caller's role is not allowed to fill. */
const NO_ACCESS = {
  users: 'Немає доступу до облікових записів',
  contacts: 'Немає доступу до контактів',
  deals: 'Немає доступу до угод',
} as const;

const toReference = (value: string | undefined): string | null => {
  const trimmed = asText(value);
  return trimmed === '' ? null : trimmed;
};

/**
 * The one form behind both order routes. Create and edit differ in what may be
 * sent, not in what is shown: monetary fields reshape the order itself, so the
 * API accepts them only while it is still a draft, and a terminal order accepts
 * nothing at all.
 */
export const useOrderForm = ({
  order,
  items,
  onSaved,
  onReload,
  isReloading = false,
}: UseOrderFormOptions): UseOrderFormResult => {
  const [form] = Form.useForm<OrderFormValues>();
  const [isDirty, setIsDirty] = useState(false);
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const { hasConflict, handleError: handleConflict, clearConflict } = useVersionConflict();

  const create = useCreateOrder();
  const update = useUpdateOrder(order?.id ?? '');

  // Each picker reads a different section, and each section is a permission of
  // its own: a field the role cannot fill is shown disabled rather than backed
  // by a request the API would answer with 403.
  const canReadUsers = useHasPermission('users', 'read');
  const canReadContacts = useHasPermission('contacts', 'read');
  const canReadDeals = useHasPermission('deals', 'read');

  useUnsavedChanges(isDirty);

  // Money follows the draft-only rule; the descriptive fields stay editable
  // until the order reaches a terminal status.
  const canEditMoney = order === undefined || isOrderEditable(order.status);
  const canSubmit =
    order === undefined || (order.status !== 'FULFILLED' && order.status !== 'CANCELLED');

  const ownerHint = canReadUsers
    ? order
      ? undefined
      : 'Порожнє поле — відповідальним стане поточний користувач'
    : NO_ACCESS.users;

  const initialValues = useMemo<Partial<OrderFormValues>>(
    () =>
      order
        ? {
            currency: order.currency,
            // The stored amounts are normalised through Money, so the fields
            // show the same scale the API keeps.
            discountTotal: Money.parse(order.discountTotal, order.currency).toWire(),
            taxTotal: Money.parse(order.taxTotal, order.currency).toWire(),
            ownerId: order.ownerId,
            ...(order.contactId === null ? {} : { contactId: order.contactId }),
            ...(order.dealId === null ? {} : { dealId: order.dealId }),
            ...(order.notes === null ? {} : { notes: order.notes }),
          }
        : { currency: DEFAULT_CURRENCY },
    [order],
  );

  const handleError = useCallback(
    (error: unknown) => {
      // Only a lost race becomes the re-read alert: a refusal the domain names
      // is answered by its own sentence, since re-reading cannot lift it.
      if (isOrderVersionConflict(error) && handleConflict(error)) return;
      if (applyServerErrors(form, error)) return;
      reportFailureWith(ORDER_ERROR_MESSAGES)(error);
    },
    [form, handleConflict, reportFailureWith],
  );

  const handleSaved = useCallback(
    (saved: Order, text: string) => {
      setIsDirty(false);
      clearConflict();
      reportSuccess(text);
      onSaved(saved);
    },
    [clearConflict, onSaved, reportSuccess],
  );

  const submit = useCallback(() => {
    void form
      .validateFields()
      .then((values) => {
        const currency = values.currency.trim().toUpperCase();
        const notes = asText(values.notes);

        if (order) {
          const input: UpdateOrderInput = {
            // The version read with the record; a stale one answers 409.
            version: order.version,
            contactId: toReference(values.contactId),
            dealId: toReference(values.dealId),
            notes: notes === '' ? null : notes,
            ...(asText(values.ownerId) === '' ? {} : { ownerId: asText(values.ownerId) }),
            // Sending a monetary field outside a draft is refused even when the
            // value is unchanged, so it is left out rather than echoed back.
            ...(canEditMoney
              ? {
                  currency,
                  discountTotal: toAmount(values.discountTotal, currency) ?? '0.00',
                  taxTotal: toAmount(values.taxTotal, currency) ?? '0.00',
                }
              : {}),
          };

          update.mutate(input, {
            onSuccess: (saved) => handleSaved(saved, 'Замовлення збережено'),
            onError: handleError,
          });
          return;
        }

        const discountTotal = toAmount(values.discountTotal, currency);
        const taxTotal = toAmount(values.taxTotal, currency);
        const ownerId = asText(values.ownerId);
        const contactId = asText(values.contactId);
        const dealId = asText(values.dealId);

        const input: CreateOrderInput = {
          currency,
          ...(ownerId === '' ? {} : { ownerId }),
          ...(contactId === '' ? {} : { contactId }),
          ...(dealId === '' ? {} : { dealId }),
          ...(discountTotal === undefined ? {} : { discountTotal }),
          ...(taxTotal === undefined ? {} : { taxTotal }),
          ...(notes === '' ? {} : { notes }),
          ...(items && items.length > 0 ? { items } : {}),
        };

        create.mutate(input, {
          onSuccess: (saved) => handleSaved(saved, 'Замовлення створено'),
          onError: handleError,
        });
      })
      // A form that failed its own rules has already marked the offending
      // fields; there is nothing further to report.
      .catch(() => undefined);
  }, [canEditMoney, create, form, handleError, handleSaved, items, order, update]);

  const reload = useCallback(() => {
    void Promise.resolve(onReload?.()).finally(() => clearConflict());
  }, [clearConflict, onReload]);

  const fields = (
    <>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item
            name="ownerId"
            label="Відповідальний"
            rules={[zodRule(orderReferenceSchema)]}
            extra={ownerHint}
          >
            {canReadUsers ? (
              <ReferenceSelect
                useOptions={useUserOptions}
                useResolved={useResolvedUser}
                getLabel={userLabel}
                disabled={!canSubmit}
                placeholder="Поточний користувач"
              />
            ) : (
              <Select disabled placeholder="Поточний користувач" />
            )}
          </Form.Item>
        </Col>

        <Col xs={24} md={8}>
          <Form.Item
            name="contactId"
            label="Контакт"
            rules={[zodRule(orderReferenceSchema)]}
            extra={canReadContacts ? undefined : NO_ACCESS.contacts}
          >
            {canReadContacts ? (
              <ReferenceSelect
                useOptions={useContactOptions}
                useResolved={useResolvedContact}
                getLabel={contactLabel}
                disabled={!canSubmit}
                placeholder="Необовʼязково"
              />
            ) : (
              <Select disabled placeholder="Необовʼязково" />
            )}
          </Form.Item>
        </Col>

        <Col xs={24} md={8}>
          <Form.Item
            name="dealId"
            label="Угода"
            rules={[zodRule(orderReferenceSchema)]}
            extra={canReadDeals ? undefined : NO_ACCESS.deals}
          >
            {canReadDeals ? (
              <ReferenceSelect
                useOptions={useDealOptions}
                useResolved={useResolvedDeal}
                getLabel={dealLabel}
                disabled={!canSubmit}
                placeholder="Необовʼязково"
              />
            ) : (
              <Select disabled placeholder="Необовʼязково" />
            )}
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item
            name="currency"
            label="Валюта"
            rules={[zodRule(orderCurrencySchema)]}
            extra={canEditMoney ? undefined : 'Змінюється лише у чернетці'}
          >
            <Input maxLength={3} disabled={!canEditMoney} placeholder={DEFAULT_CURRENCY} />
          </Form.Item>
        </Col>

        <Col xs={12} md={8}>
          <Form.Item name="discountTotal" label="Знижка" rules={[zodRule(orderAmountSchema)]}>
            <Input
              className="numeric"
              inputMode="decimal"
              disabled={!canEditMoney}
              placeholder="0.00"
            />
          </Form.Item>
        </Col>

        <Col xs={12} md={8}>
          <Form.Item name="taxTotal" label="Податок" rules={[zodRule(orderAmountSchema)]}>
            <Input
              className="numeric"
              inputMode="decimal"
              disabled={!canEditMoney}
              placeholder="0.00"
            />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name="notes" label="Примітки" rules={[zodRule(orderNotesSchema)]}>
        <Input.TextArea
          rows={3}
          maxLength={4000}
          showCount
          disabled={!canSubmit}
          placeholder="Необовʼязково"
        />
      </Form.Item>
    </>
  );

  return {
    formProps: {
      form,
      initialValues,
      layout: 'vertical',
      requiredMark: false,
      onValuesChange: () => setIsDirty(true),
      onFinish: submit,
    },
    fields,
    conflictAlert: <ConflictAlert open={hasConflict} onReload={reload} isReloading={isReloading} />,
    submit,
    isSaving: create.isPending || update.isPending,
    canSubmit,
    handleError,
  };
};
