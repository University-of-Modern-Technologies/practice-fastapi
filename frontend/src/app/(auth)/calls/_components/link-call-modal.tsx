'use client';

import { Alert, Form, Select, Typography } from 'antd';
import { useEffect } from 'react';
import { FormModal, ReferenceSelect } from '@/components';
import { ApiError } from '@/shared/api';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import {
  contactLabel,
  useContactOptions,
  useResolvedContact,
} from '../../contacts/contacts.queries';
import { dealLabel, useDealOptions, useResolvedDeal } from '../../deals/deals.queries';
import { useLinkCall } from '../calls.queries';
import { CALL_ERROR, type Call } from '../calls.types';
import type { CallLinkFormValues } from '../calls.validation';

interface LinkCallModalProps {
  /** The call being attributed; nothing is shown until the action is started. */
  readonly call: Call | null;
  readonly onCancel: () => void;
  readonly onLinked: () => void;
  /** A lost race is shown by the card, which owns the re-read. */
  readonly onConflict: (error: unknown) => boolean;
}

/**
 * Attributing a call to what it was about.
 *
 * This is a separate action and not a pair of fields on the edit form, because
 * that is what the API says it is: `POST /calls/:id/link` is audited as
 * `call.linked`, and a call gaining a contact is the event the journal is kept
 * for. Folding it into a PATCH would record it as "somebody edited a call".
 */
export function LinkCallModal({ call, onCancel, onLinked, onConflict }: LinkCallModalProps) {
  const [form] = Form.useForm<CallLinkFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const link = useLinkCall(call?.id ?? '');

  // Reading contacts and deals are separate permissions: without them the
  // pickers are not mounted at all, so the dialog never fires a request the
  // caller may not make.
  const canReadContacts = useHasPermission('contacts', 'read');
  const canReadDeals = useHasPermission('deals', 'read');

  /**
   * The dialog opens empty, and deliberately not pre-filled with what the call
   * is already attached to. This action can only attach: the API refuses a
   * `null` here, so a picker that showed the current contact would invite the
   * operator to clear it — and clearing it would do nothing at all. Detaching
   * is its own control on the card.
   *
   * Clearing the fields on every open also keeps one call's pick out of the
   * next call's dialog, since the dialog is mounted once and reused.
   */
  useEffect(() => {
    if (call === null) return;
    form.setFieldsValue({ contactId: undefined, dealId: undefined });
  }, [call, form]);

  const submit = (): void => {
    if (call === null) return;

    void form
      .validateFields()
      .then((values) => {
        const contactId = values.contactId?.trim();
        const dealId = values.dealId?.trim();

        if (!contactId && !dealId) {
          form.setFields([{ name: 'contactId', errors: ['Виберіть контакт або угоду'] }]);
          return;
        }

        link.mutate(
          {
            // The version the card read: the link is made to the record the
            // operator was looking at.
            version: call.version,
            ...(contactId ? { contactId } : {}),
            ...(dealId ? { dealId } : {}),
          },
          {
            onSuccess: () => {
              reportSuccess('Дзвінок привʼязано');
              onLinked();
            },
            onError: (error: unknown) => {
              if (onConflict(error)) {
                onCancel();
                return;
              }
              if (error instanceof ApiError) {
                // A reference the API cannot resolve belongs on the field that
                // names it: the user has one picker to change.
                if (error.code === CALL_ERROR.contactNotFound) {
                  form.setFields([{ name: 'contactId', errors: ['Такого контакту вже немає'] }]);
                  return;
                }
                if (error.code === CALL_ERROR.dealNotFound) {
                  form.setFields([{ name: 'dealId', errors: ['Такої угоди вже немає'] }]);
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
      open={call !== null}
      title="Привʼязати дзвінок"
      isSaving={link.isPending}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Привʼязати"
      width={520}
    >
      {call === null ? null : (
        <>
          <Typography.Paragraph type="secondary">
            Дзвінок {call.fromNumber} → {call.toNumber}. Можна вказати контакт, угоду або обидва.
            Щоб зняти наявний звʼязок, скористайтеся кнопкою «Відвʼязати» в картці.
          </Typography.Paragraph>

          {canReadContacts || canReadDeals ? null : (
            <Alert
              type="warning"
              showIcon
              className="mb-4"
              message="Немає доступу ні до контактів, ні до угод"
              description="Привʼязати дзвінок можна лише до записів, які ви маєте право читати."
            />
          )}

          <Form<CallLinkFormValues> form={form} layout="vertical" requiredMark={false}>
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

            <Form.Item
              name="dealId"
              label="Угода"
              extra={canReadDeals ? undefined : 'Немає доступу до угод'}
            >
              {canReadDeals ? (
                <ReferenceSelect
                  useOptions={useDealOptions}
                  useResolved={useResolvedDeal}
                  getLabel={dealLabel}
                  placeholder="Не привʼязано"
                />
              ) : (
                <Select disabled placeholder="Не привʼязано" />
              )}
            </Form.Item>
          </Form>
        </>
      )}
    </FormModal>
  );
}
