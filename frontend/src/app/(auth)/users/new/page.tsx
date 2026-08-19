'use client';

import { Form } from 'antd';
import { useRouter } from 'next/navigation';
import { FormCard, PageHeader, PermissionGate } from '@/components';
import { useUserForm } from '../_hooks';
import type { UserFormValues } from '../users.types';

function CreateUserForm() {
  const router = useRouter();
  const { form, fields, isSaving, submit } = useUserForm({
    onSaved: (user) => router.replace(`/users/${user.id}`),
  });

  return (
    <>
      <PageHeader title="Новий користувач" description="Пошта, пароль і ролі облікового запису" />

      <FormCard
        title="Обліковий запис"
        isSaving={isSaving}
        onSubmit={submit}
        submitLabel="Створити"
        backHref="/users"
      >
        <Form<UserFormValues> form={form} layout="vertical" requiredMark onFinish={submit}>
          {fields}
        </Form>
      </FormCard>
    </>
  );
}

export default function NewUserPage() {
  return (
    <PermissionGate resource="users" action="create">
      <CreateUserForm />
    </PermissionGate>
  );
}
