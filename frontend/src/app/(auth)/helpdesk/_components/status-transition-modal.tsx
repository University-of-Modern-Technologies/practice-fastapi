'use client';

import { Alert, Form, Input, Typography } from 'antd';
import { useEffect } from 'react';
import { FormModal, StatusTag, zodRule } from '@/components';
import { TICKET_STATUS, type TicketStatus } from '@/shared/constants';
import {
  TICKET_NOTE_MAX,
  ticketNoteSchema,
  type TicketTransitionFormValues,
} from '../helpdesk.validation';

interface StatusTransitionModalProps {
  /** The status being moved to; nothing is shown until a button picks one. */
  readonly target: TicketStatus | null;
  readonly isSaving: boolean;
  readonly onCancel: () => void;
  readonly onSubmit: (note: string | undefined) => void;
}

/** Wording for the two moves that also change what the record claims about itself. */
const NOTICE: Partial<Record<TicketStatus, string>> = {
  RESOLVED: 'Разом зі станом буде проставлено дату розвʼязання',
  OPEN: 'Повернення в роботу знімає дату розвʼязання',
  CLOSED: 'Закрите звернення більше не можна перевести в інший стан',
};

/**
 * Confirms a move along the status machine. The status itself is not chosen
 * here — the caller offers only the moves the machine allows — so the dialog
 * asks for the one value that may travel with it.
 */
export function StatusTransitionModal({
  target,
  isSaving,
  onCancel,
  onSubmit,
}: StatusTransitionModalProps) {
  const [form] = Form.useForm<TicketTransitionFormValues>();

  // The dialog is mounted once and reused, so the note is cleared whenever a
  // different move is picked; without this it would carry the previous comment
  // into an unrelated transition.
  useEffect(() => {
    if (target !== null) form.setFieldsValue({ note: '' });
  }, [form, target]);

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => onSubmit(values.note?.trim() || undefined))
      // A field that failed its own rule already shows why.
      .catch(() => undefined);
  };

  const notice = target === null ? undefined : NOTICE[target];

  return (
    <FormModal
      open={target !== null}
      title="Змінити стан звернення"
      isSaving={isSaving}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Перевести"
      width={520}
    >
      {target === null ? null : (
        <>
          <Typography.Paragraph>
            Новий стан: <StatusTag dictionary={TICKET_STATUS} value={target} />
          </Typography.Paragraph>

          {notice === undefined ? null : (
            <Alert type="info" showIcon className="mb-4" message={notice} />
          )}

          <Form<TicketTransitionFormValues> form={form} layout="vertical" requiredMark={false}>
            <Form.Item
              name="note"
              label="Коментар"
              extra="Необовʼязково. Залишається в історії стану звернення."
              rules={[zodRule(ticketNoteSchema)]}
            >
              <Input.TextArea
                rows={3}
                maxLength={TICKET_NOTE_MAX}
                showCount
                placeholder="Що змінилося і чому"
              />
            </Form.Item>
          </Form>
        </>
      )}
    </FormModal>
  );
}
