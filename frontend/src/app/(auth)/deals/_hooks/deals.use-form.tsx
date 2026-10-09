'use client';

import { Col, DatePicker, Form, Input, InputNumber, Row, Select, type FormInstance } from 'antd';
import { useCallback, useMemo, type ReactNode } from 'react';
import { ConflictAlert, ReferenceSelect, applyServerErrors, zodRule } from '@/components';
import { DateTime } from '@/lib/date-time';
import { DEFAULT_CURRENCY, Money } from '@/lib/money';
import { ApiError } from '@/shared/api';
import { DEAL_STAGE_PROBABILITY } from '@/shared/constants';
import { useHasPermission, useMutationFeedback, useRecordForm } from '@/shared/hooks';
import {
  contactLabel,
  useContactOptions,
  useResolvedContact,
} from '../../contacts/contacts.queries';
import { useCreateDeal, useUpdateDeal } from '../deals.queries';
import { DEAL_ERROR, type CreateDealInput, type Deal, type UpdateDealInput } from '../deals.types';
import {
  CERTAIN_PROBABILITY,
  dealAmountSchema,
  dealCurrencySchema,
  dealProbabilitySchema,
  dealTitleSchema,
  type DealFormValues,
} from '../deals.validation';

interface UseDealFormOptions {
  /** Absent on the create route; present, and the form edits that record. */
  readonly deal?: Deal | undefined;
  readonly onSaved: (deal: Deal) => void;
  /** Re-reads the record after a lost race; the form then shows it with its version. */
  readonly onReload?:
    (() => Promise<{ readonly data?: Deal | undefined; readonly isError?: boolean }>) | undefined;
  readonly isReloading?: boolean | undefined;
}

interface UseDealFormResult {
  readonly formProps: {
    readonly form: FormInstance<DealFormValues>;
    readonly initialValues: Partial<DealFormValues>;
    readonly layout: 'vertical';
    readonly requiredMark: boolean;
    readonly onValuesChange: () => void;
    readonly onFinish: () => void;
  };
  readonly fields: ReactNode;
  readonly conflictAlert: ReactNode;
  readonly submit: () => void;
  readonly isSaving: boolean;
  /** Routes a failed write to the field it belongs to; also used by the delete action. */
  readonly handleError: (error: unknown) => void;
}

/**
 * A deal as the form shows it. Every field is named, absent ones included, so
 * a re-read clears a value the other person removed instead of keeping ours.
 */
const toDealValues = (deal: Deal): Partial<DealFormValues> => ({
  title: deal.title,
  // The stored amount is normalised through Money, so the field shows the same
  // scale the API keeps rather than whatever it was typed as.
  amount: Money.parse(deal.amount, deal.currency).toWire(),
  currency: deal.currency,
  probability: deal.probability,
  expectedCloseDate: DateTime.toPicker(deal.expectedCloseDate),
  contactId: deal.contactId ?? undefined,
});

/**
 * The one form behind both deal routes. `stage` is absent from it by design:
 * the stage only moves through `POST /deals/:id/transitions`, so a field for it
 * here would offer the user a change the API refuses to make this way.
 */
export const useDealForm = ({
  deal,
  onSaved,
  onReload,
  isReloading = false,
}: UseDealFormOptions): UseDealFormResult => {
  const [form] = Form.useForm<DealFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();
  // `base` is the copy on screen: its values are in the fields and its version
  // is the one a save sends, even after a fresher copy reached the cache.
  const { base, markDirty, adopt, hasConflict, handleConflict, reload } = useRecordForm({
    form,
    record: deal,
    toValues: toDealValues,
    onReload,
  });

  const create = useCreateDeal();
  const update = useUpdateDeal(deal?.id ?? '');

  // Reading contacts is a separate permission: without it the picker is not
  // mounted at all, so the form never fires a request it may not make.
  const canReadContacts = useHasPermission('contacts', 'read');

  /**
   * A terminal stage fixes the odds, and a PATCH is validated against the stage
   * the record already has — so the field is locked there instead of letting
   * the user send a value the API will refuse.
   */
  const fixedProbability = DEAL_STAGE_PROBABILITY[base?.stage ?? 'LEAD'];

  const probabilitySchema = useMemo(
    () =>
      fixedProbability === null
        ? dealProbabilitySchema.refine((value) => value !== CERTAIN_PROBABILITY, {
            message: 'Ймовірність 100 % можлива лише для виграної угоди',
          })
        : dealProbabilitySchema,
    [fixedProbability],
  );

  // Read once, at mount; every later copy reaches the fields through the hook.
  const initialValues = useMemo<Partial<DealFormValues>>(
    () => (base ? toDealValues(base) : { currency: DEFAULT_CURRENCY, probability: 10 }),
    [base],
  );

  const handleError = useCallback(
    (error: unknown) => {
      if (handleConflict(error)) return;

      // The refused odds belong on the field that caused them: the user has one
      // number to change, not a form to re-read.
      if (error instanceof ApiError && error.code === DEAL_ERROR.probability) {
        form.setFields([
          { name: 'probability', errors: ['Ймовірність не відповідає поточній стадії'] },
        ]);
        return;
      }

      if (applyServerErrors(form, error)) return;
      reportFailure(error);
    },
    [form, handleConflict, reportFailure],
  );

  const handleSaved = useCallback(
    (saved: Deal, text: string) => {
      adopt(saved);
      reportSuccess(text);
      onSaved(saved);
    },
    [adopt, onSaved, reportSuccess],
  );

  const submit = useCallback(() => {
    void form
      .validateFields()
      .then((values) => {
        const currency = values.currency.trim().toUpperCase();
        const amount = Money.fromInput(values.amount, currency).toWire();
        const expectedCloseDate = DateTime.toWireDate(values.expectedCloseDate);

        if (base) {
          const input: UpdateDealInput = {
            // The version of the copy the user edited; a stale one answers 409.
            version: base.version,
            title: values.title.trim(),
            contactId: values.contactId ?? null,
            amount,
            currency,
            // A locked field carries the value the stage already dictates,
            // so sending it back would only be noise.
            ...(fixedProbability === null ? { probability: values.probability } : {}),
            expectedCloseDate: expectedCloseDate ?? null,
          };

          update.mutate(input, {
            onSuccess: (saved) => handleSaved(saved, 'Угоду збережено'),
            onError: handleError,
          });
          return;
        }

        const input: CreateDealInput = {
          title: values.title.trim(),
          amount,
          currency,
          probability: values.probability,
          ...(values.contactId ? { contactId: values.contactId } : {}),
          ...(expectedCloseDate ? { expectedCloseDate } : {}),
        };

        create.mutate(input, {
          onSuccess: (saved) => handleSaved(saved, 'Угоду створено'),
          onError: handleError,
        });
      })
      // A form that failed its own rules has already marked the offending
      // fields; there is nothing further to report.
      .catch(() => undefined);
  }, [base, create, fixedProbability, form, handleError, handleSaved, update]);

  const fields = (
    <>
      <Row gutter={16}>
        <Col xs={24} md={16}>
          <Form.Item name="title" label="Назва" rules={[zodRule(dealTitleSchema)]}>
            <Input autoFocus placeholder="Назва угоди" maxLength={160} />
          </Form.Item>
        </Col>

        <Col xs={24} md={8}>
          <Form.Item
            name="contactId"
            label="Контакт"
            extra={canReadContacts ? undefined : 'Немає доступу до контактів'}
          >
            {canReadContacts ? (
              <ReferenceSelect
                useOptions={useContactOptions}
                useResolved={useResolvedContact}
                getLabel={contactLabel}
                placeholder="Не привʼязано"
              />
            ) : (
              <Select disabled placeholder="Не привʼязано" />
            )}
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={12} md={8}>
          <Form.Item name="amount" label="Сума" rules={[zodRule(dealAmountSchema)]}>
            <Input className="numeric" inputMode="decimal" placeholder="12000.00" />
          </Form.Item>
        </Col>

        <Col xs={12} md={8}>
          <Form.Item name="currency" label="Валюта" rules={[zodRule(dealCurrencySchema)]}>
            <Input maxLength={3} placeholder={DEFAULT_CURRENCY} />
          </Form.Item>
        </Col>

        <Col xs={12} md={8}>
          <Form.Item
            name="probability"
            label="Ймовірність, %"
            rules={[zodRule(probabilitySchema)]}
            extra={
              fixedProbability === null
                ? '100 % — тільки для виграної угоди'
                : 'Стадію закрито: значення фіксоване'
            }
          >
            <InputNumber
              min={0}
              max={100}
              step={5}
              precision={0}
              style={{ width: '100%' }}
              disabled={fixedProbability !== null}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item name="expectedCloseDate" label="Очікуване закриття">
            <DatePicker style={{ width: '100%' }} placeholder="Оберіть дату" />
          </Form.Item>
        </Col>
      </Row>
    </>
  );

  return {
    formProps: {
      form,
      initialValues,
      layout: 'vertical',
      requiredMark: false,
      onValuesChange: markDirty,
      onFinish: submit,
    },
    fields,
    conflictAlert: <ConflictAlert open={hasConflict} onReload={reload} isReloading={isReloading} />,
    submit,
    isSaving: create.isPending || update.isPending,
    handleError,
  };
};
