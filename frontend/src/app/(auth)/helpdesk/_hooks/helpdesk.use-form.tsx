'use client';

import { Col, Form, Input, Row, Select, type FormInstance } from 'antd';
import { useCallback, useMemo, type ReactNode } from 'react';
import { ConflictAlert, ReferenceSelect, applyServerErrors, zodRule } from '@/components';
import { ApiError } from '@/shared/api';
import { useHasPermission, useMutationFeedback, useRecordForm } from '@/shared/hooks';
import {
  contactLabel,
  useContactOptions,
  useResolvedContact,
} from '../../contacts/contacts.queries';
import { useResolvedUser, useUserOptions, userLabel } from '../../users/users.queries';
import { useCreateTicket, useUpdateTicket } from '../helpdesk.queries';
import {
  TICKET_ERROR,
  type CreateTicketInput,
  type Ticket,
  type UpdateTicketInput,
} from '../helpdesk.types';
import {
  TICKET_CHANNEL,
  TICKET_CHANNELS,
  TICKET_PRIORITIES,
  TICKET_PRIORITY,
} from '@/shared/constants';
import {
  TICKET_BODY_MAX,
  TICKET_SUBJECT_MAX,
  ticketBodySchema,
  ticketSubjectSchema,
  type TicketFormValues,
} from '../helpdesk.validation';

const CHANNEL_OPTIONS = TICKET_CHANNELS.map((channel) => ({
  value: channel,
  label: TICKET_CHANNEL[channel].label,
}));

const PRIORITY_OPTIONS = TICKET_PRIORITIES.map((priority) => ({
  value: priority,
  label: TICKET_PRIORITY[priority].label,
}));

interface UseTicketFormOptions {
  /** Absent on the create route; present, and the form edits that record. */
  readonly ticket?: Ticket | undefined;
  readonly onSaved: (ticket: Ticket) => void;
  /** Re-reads the record after a lost race; the form then shows it with its version. */
  readonly onReload?:
    (() => Promise<{ readonly data?: Ticket | undefined; readonly isError?: boolean }>) | undefined;
  readonly isReloading?: boolean | undefined;
}

interface UseTicketFormResult {
  readonly formProps: {
    readonly form: FormInstance<TicketFormValues>;
    readonly initialValues: Partial<TicketFormValues>;
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
 * A ticket as the form shows it. Every field is named, absent ones included,
 * so a re-read clears a value the other person removed instead of keeping ours.
 */
const toTicketValues = (ticket: Ticket): Partial<TicketFormValues> => ({
  subject: ticket.subject,
  body: ticket.body,
  channel: ticket.channel,
  priority: ticket.priority,
  ownerId: ticket.ownerId,
  contactId: ticket.contactId ?? undefined,
  assigneeId: ticket.assigneeId ?? undefined,
});

/**
 * The one form behind both helpdesk routes. `status` is absent from it by
 * design: the status only moves through
 * `POST /helpdesk/tickets/:id/transitions`, so a field for it here would offer
 * the user a change the API refuses to make this way.
 */
export const useTicketForm = ({
  ticket,
  onSaved,
  onReload,
  isReloading = false,
}: UseTicketFormOptions): UseTicketFormResult => {
  const [form] = Form.useForm<TicketFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();
  // `base` is the copy on screen: its values are in the fields and its version
  // is the one a save sends, even after a fresher copy reached the cache.
  const { base, markDirty, adopt, hasConflict, handleConflict, reload } = useRecordForm({
    form,
    record: ticket,
    toValues: toTicketValues,
    onReload,
  });

  const create = useCreateTicket();
  const update = useUpdateTicket(ticket?.id ?? '');

  // Reading contacts and accounts are separate permissions: without them the
  // pickers are not mounted at all, so the form never fires a request it may
  // not make.
  const canReadContacts = useHasPermission('contacts', 'read');
  const canReadUsers = useHasPermission('users', 'read');

  // Read once, at mount; every later copy reaches the fields through the hook.
  const initialValues = useMemo<Partial<TicketFormValues>>(
    () => (base ? toTicketValues(base) : { channel: 'EMAIL', priority: 'NORMAL' }),
    [base],
  );

  const handleError = useCallback(
    (error: unknown) => {
      if (handleConflict(error)) return;

      if (error instanceof ApiError) {
        // A reference the API cannot resolve belongs on the field that names
        // it: the user has one picker to change, not a form to re-read.
        if (error.code === TICKET_ERROR.contactNotFound) {
          form.setFields([{ name: 'contactId', errors: ['Такого контакту вже немає'] }]);
          return;
        }
        if (error.code === TICKET_ERROR.assigneeNotFound) {
          form.setFields([{ name: 'assigneeId', errors: ['Такого виконавця вже немає'] }]);
          return;
        }
        // Handing a record to somebody else is refused with 403 rather than
        // with a code of its own, so the status is what identifies it here.
        if (error.isForbidden && base && form.getFieldValue('ownerId') !== base.ownerId) {
          form.setFields([
            { name: 'ownerId', errors: ['Немає прав призначити звернення іншому власнику'] },
          ]);
          return;
        }
      }

      if (applyServerErrors(form, error)) return;
      reportFailure(error);
    },
    [base, form, handleConflict, reportFailure],
  );

  const handleSaved = useCallback(
    (saved: Ticket, text: string) => {
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
        if (base) {
          const input: UpdateTicketInput = {
            // The version of the copy the user edited; a stale one answers 409.
            version: base.version,
            subject: values.subject.trim(),
            body: values.body.trim(),
            channel: values.channel,
            priority: values.priority,
            contactId: values.contactId ?? null,
            assigneeId: values.assigneeId ?? null,
            // An owner is never cleared, so an empty picker means "leave it".
            ...(values.ownerId ? { ownerId: values.ownerId } : {}),
          };

          update.mutate(input, {
            onSuccess: (saved) => handleSaved(saved, 'Звернення збережено'),
            onError: handleError,
          });
          return;
        }

        const input: CreateTicketInput = {
          subject: values.subject.trim(),
          body: values.body.trim(),
          channel: values.channel,
          priority: values.priority,
          ...(values.contactId ? { contactId: values.contactId } : {}),
          ...(values.assigneeId ? { assigneeId: values.assigneeId } : {}),
          ...(values.ownerId ? { ownerId: values.ownerId } : {}),
        };

        create.mutate(input, {
          onSuccess: (saved) => handleSaved(saved, 'Звернення створено'),
          onError: handleError,
        });
      })
      // A form that failed its own rules has already marked the offending
      // fields; there is nothing further to report.
      .catch(() => undefined);
  }, [base, create, form, handleError, handleSaved, update]);

  const userPicker = (placeholder: string): ReactNode =>
    canReadUsers ? (
      <ReferenceSelect
        useOptions={useUserOptions}
        useResolved={useResolvedUser}
        getLabel={userLabel}
        placeholder={placeholder}
      />
    ) : (
      <Select disabled placeholder={placeholder} />
    );

  const fields = (
    <>
      <Row gutter={16}>
        <Col xs={24} md={16}>
          <Form.Item name="subject" label="Тема" rules={[zodRule(ticketSubjectSchema)]}>
            <Input autoFocus placeholder="Коротко про звернення" maxLength={TICKET_SUBJECT_MAX} />
          </Form.Item>
        </Col>

        <Col xs={12} md={4}>
          <Form.Item name="channel" label="Канал">
            <Select options={CHANNEL_OPTIONS} />
          </Form.Item>
        </Col>

        <Col xs={12} md={4}>
          <Form.Item name="priority" label="Пріоритет">
            <Select options={PRIORITY_OPTIONS} />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24}>
          <Form.Item name="body" label="Опис" rules={[zodRule(ticketBodySchema)]}>
            <Input.TextArea
              rows={6}
              maxLength={TICKET_BODY_MAX}
              showCount
              placeholder="Що саме сталося, чого очікує клієнт, що вже перевірено"
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
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

        <Col xs={24} md={8}>
          <Form.Item
            name="assigneeId"
            label="Виконавець"
            extra={canReadUsers ? undefined : 'Немає доступу до облікових записів'}
          >
            {userPicker('Не призначено')}
          </Form.Item>
        </Col>

        <Col xs={24} md={8}>
          <Form.Item
            name="ownerId"
            label="Відповідальний"
            extra="Від цього поля залежить, хто бачить звернення з обмеженою областю"
          >
            {userPicker('Поточний користувач')}
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
