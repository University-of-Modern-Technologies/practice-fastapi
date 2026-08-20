'use client';

import { Alert, Col, Form, Input, Row } from 'antd';
import { useRouter } from 'next/navigation';
import { useCallback, useState, type ReactNode } from 'react';
// `required` on the item draws the asterisk; the message itself comes from the
// same schema the API mirrors, so a field is described in exactly one place.
import { applyServerErrors, zodRule } from '@/components';
import { ApiError } from '@/shared/api';
import { useMutationFeedback, useUnsavedChanges } from '@/shared/hooks';
import { ERROR_CODE } from '@/types/domain';
import { useCreateContact, useUpdateContact } from '../contacts.queries';
import type {
  Contact,
  ContactFormValues,
  CreateContactInput,
  UpdateContactInput,
} from '../contacts.types';
import { CONTACT_CHANNEL_MESSAGE, contactSchemas, hasContactChannel } from '../contacts.validation';

const CLEARABLE_FIELDS = ['email', 'phone', 'company', 'notes'] as const;

const DUPLICATE_MESSAGE = 'Контакт із такою поштою або телефоном уже існує';

const trimmed = (value: string | undefined): string | undefined => value?.trim() || undefined;

const toCreateInput = (values: ContactFormValues): CreateContactInput => ({
  firstName: values.firstName.trim(),
  lastName: values.lastName.trim(),
  email: trimmed(values.email),
  phone: trimmed(values.phone),
  company: trimmed(values.company),
  notes: trimmed(values.notes),
});

/**
 * Only what the user actually changed goes on the wire. A field emptied on
 * screen becomes an explicit `null` — "clear this" — while a field left alone
 * stays out of the body entirely, so two people editing different fields of the
 * same contact do not overwrite each other.
 */
const toUpdateInput = (initial: Contact, values: ContactFormValues): UpdateContactInput => {
  const patch: Record<string, string | null> = {};

  const firstName = values.firstName.trim();
  if (firstName !== initial.firstName) patch.firstName = firstName;

  const lastName = values.lastName.trim();
  if (lastName !== initial.lastName) patch.lastName = lastName;

  for (const field of CLEARABLE_FIELDS) {
    const next = values[field]?.trim() || null;
    if (next !== initial[field]) patch[field] = next;
  }

  return patch as UpdateContactInput;
};

const toFormValues = (contact: Contact): ContactFormValues => ({
  firstName: contact.firstName,
  lastName: contact.lastName,
  email: contact.email ?? undefined,
  phone: contact.phone ?? undefined,
  company: contact.company ?? undefined,
  notes: contact.notes ?? undefined,
});

interface UseContactFormOptions {
  /** The record being edited. Absent means the form creates a new contact. */
  readonly contact?: Contact | undefined;
}

interface UseContactFormResult {
  readonly isEditMode: boolean;
  readonly isSaving: boolean;
  readonly hasChanges: boolean;
  readonly formElement: ReactNode;
  readonly submit: () => void;
}

/**
 * One hook behind both the create page and the card. Two hooks would drift:
 * a field added to one form would quietly go missing from the other.
 */
export const useContactForm = ({ contact }: UseContactFormOptions = {}): UseContactFormResult => {
  const [form] = Form.useForm<ContactFormValues>();
  const router = useRouter();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const isEditMode = contact !== undefined;
  const [hasChanges, setHasChanges] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);

  const createContact = useCreateContact();
  const updateContact = useUpdateContact(contact?.id ?? '');

  useUnsavedChanges(hasChanges);

  const showChannelError = useCallback(() => {
    setChannelError(CONTACT_CHANNEL_MESSAGE);
    form.setFields([
      { name: 'email', errors: [CONTACT_CHANNEL_MESSAGE] },
      { name: 'phone', errors: [CONTACT_CHANNEL_MESSAGE] },
    ]);
  }, [form]);

  const reportSaveError = useCallback(
    (error: unknown) => {
      // The API states this refusal in its own code, so it becomes a message
      // under the two fields it concerns instead of a generic "check the data".
      if (error instanceof ApiError && error.code === ERROR_CODE.contactChannelRequired) {
        showChannelError();
        return;
      }
      if (error instanceof ApiError && error.code === 'CONTACT_DUPLICATE') {
        setDuplicateError(DUPLICATE_MESSAGE);
        return;
      }
      if (applyServerErrors(form, error)) return;
      reportFailure(error);
    },
    [form, reportFailure, showChannelError],
  );

  const save = useCallback(
    async (values: ContactFormValues) => {
      setChannelError(null);
      setDuplicateError(null);

      if (!hasContactChannel(values)) {
        showChannelError();
        return;
      }

      try {
        if (contact) {
          const patch = toUpdateInput(contact, values);
          if (Object.keys(patch).length === 0) {
            reportSuccess('Змін немає');
            setHasChanges(false);
            return;
          }
          await updateContact.mutateAsync(patch);
          setHasChanges(false);
          reportSuccess('Контакт збережено');
          return;
        }

        const created = await createContact.mutateAsync(toCreateInput(values));
        setHasChanges(false);
        reportSuccess('Контакт створено');
        router.push(`/contacts/${created.id}`);
      } catch (error) {
        reportSaveError(error);
      }
    },
    [
      contact,
      createContact,
      updateContact,
      router,
      reportSuccess,
      reportSaveError,
      showChannelError,
    ],
  );

  const submit = useCallback(() => form.submit(), [form]);

  const formElement = (
    <Form<ContactFormValues>
      form={form}
      layout="vertical"
      requiredMark
      {...(contact ? { initialValues: toFormValues(contact) } : {})}
      onValuesChange={() => setHasChanges(true)}
      onFinish={(values) => void save(values)}
    >
      {channelError ? (
        <Alert type="warning" showIcon className="mb-4" message={channelError} />
      ) : null}
      {duplicateError ? (
        <Alert type="error" showIcon className="mb-4" message={duplicateError} />
      ) : null}

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="lastName"
            label="Прізвище"
            required
            rules={[zodRule(contactSchemas.lastName)]}
          >
            <Input autoFocus maxLength={80} placeholder="Ковальчук" />
          </Form.Item>
        </Col>

        <Col xs={24} md={12}>
          <Form.Item
            name="firstName"
            label="Імʼя"
            required
            rules={[zodRule(contactSchemas.firstName)]}
          >
            <Input maxLength={80} placeholder="Олена" />
          </Form.Item>
        </Col>

        <Col xs={24} md={12}>
          <Form.Item
            name="email"
            label="Пошта"
            extra="Пошта або телефон — щонайменше одне поле"
            rules={[zodRule(contactSchemas.email)]}
          >
            <Input autoComplete="email" maxLength={320} placeholder="olena@example.com" />
          </Form.Item>
        </Col>

        <Col xs={24} md={12}>
          <Form.Item name="phone" label="Телефон" rules={[zodRule(contactSchemas.phone)]}>
            <Input autoComplete="tel" maxLength={32} placeholder="+380 50 123 45 67" />
          </Form.Item>
        </Col>

        <Col xs={24}>
          <Form.Item name="company" label="Компанія" rules={[zodRule(contactSchemas.company)]}>
            <Input maxLength={160} placeholder="ТОВ «Приклад»" />
          </Form.Item>
        </Col>

        <Col xs={24}>
          <Form.Item name="notes" label="Нотатки" rules={[zodRule(contactSchemas.notes)]}>
            <Input.TextArea rows={4} placeholder="Домовленості, контекст, наступні кроки" />
          </Form.Item>
        </Col>
      </Row>
    </Form>
  );

  return {
    isEditMode,
    isSaving: createContact.isPending || updateContact.isPending,
    hasChanges,
    formElement,
    submit,
  };
};
