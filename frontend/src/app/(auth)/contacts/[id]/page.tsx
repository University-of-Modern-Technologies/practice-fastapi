'use client';

import { Button, Descriptions, Result } from 'antd';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  CopyableValue,
  DateValue,
  DeleteConfirm,
  FormCard,
  FormPageSkeleton,
  PageHeader,
  PermissionGate,
} from '@/components';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { useContact, useDeleteContact } from '../contacts.queries';
import type { Contact } from '../contacts.types';
import { useContactForm } from '../_hooks';

function ContactCard({ contact }: { readonly contact: Contact }) {
  const router = useRouter();
  const { formElement, submit, isSaving } = useContactForm({ contact });
  const deleteContact = useDeleteContact();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const onDelete = () => {
    deleteContact.mutate(contact.id, {
      onSuccess: () => {
        reportSuccess('Контакт видалено');
        router.push('/contacts');
      },
      onError: reportFailure,
    });
  };

  return (
    <>
      <PageHeader
        title={`${contact.lastName} ${contact.firstName}`}
        description={contact.company ?? 'Без компанії'}
      />

      <FormCard
        title="Дані контакту"
        backHref="/contacts"
        extra={
          <>
            <PermissionGate resource="contacts" action="delete" fallback={null}>
              <DeleteConfirm
                title="Видалити контакт?"
                description="Контакт зникне зі списків і звітів."
                isPending={deleteContact.isPending}
                onConfirm={onDelete}
              >
                <Button danger>Видалити</Button>
              </DeleteConfirm>
            </PermissionGate>

            <PermissionGate resource="contacts" action="write" fallback={null}>
              <Button type="primary" loading={isSaving} onClick={submit}>
                Зберегти
              </Button>
            </PermissionGate>
          </>
        }
      >
        {formElement}

        <Descriptions size="small" column={{ xs: 1, md: 3 }} className="mt-2">
          <Descriptions.Item label="Ідентифікатор">
            <CopyableValue value={contact.id} />
          </Descriptions.Item>
          <Descriptions.Item label="Створено">
            <DateValue value={contact.createdAt} withTime />
          </Descriptions.Item>
          <Descriptions.Item label="Оновлено">
            <DateValue value={contact.updatedAt} withTime />
          </Descriptions.Item>
        </Descriptions>
      </FormCard>
    </>
  );
}

function ContactDetails() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const { data: contact, isLoading, error } = useContact(id);

  if (error instanceof ApiError && error.status === 404) {
    return (
      <Result
        status="404"
        title="Контакт не знайдено"
        subTitle="Запис міг бути видалений або недоступний вашій ролі."
        extra={
          <Link href="/contacts">
            <Button type="primary">До списку</Button>
          </Link>
        }
      />
    );
  }

  if (isLoading || !contact) return <FormPageSkeleton />;

  // Remounting on the id keeps the form's initial values in step with the
  // record when the user moves from one card to another.
  return <ContactCard key={contact.id} contact={contact} />;
}

export default function ContactPage() {
  return (
    <PermissionGate resource="contacts" action="read">
      <ContactDetails />
    </PermissionGate>
  );
}
