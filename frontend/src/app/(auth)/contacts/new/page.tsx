'use client';

import { FormCard, PageHeader, PermissionGate } from '@/components';
import { useContactForm } from '../_hooks';

function CreateContactForm() {
  const { formElement, submit, isSaving } = useContactForm();

  return (
    <>
      <PageHeader title="Новий контакт" description="Пошта або телефон обовʼязкові" />
      <FormCard
        title="Дані контакту"
        onSubmit={submit}
        isSaving={isSaving}
        submitLabel="Створити"
        backHref="/contacts"
      >
        {formElement}
      </FormCard>
    </>
  );
}

export default function NewContactPage() {
  return (
    <PermissionGate resource="contacts" action="write">
      <CreateContactForm />
    </PermissionGate>
  );
}
