'use client';

import { Button, Card, Descriptions, Form, Result, Tag } from 'antd';
import Link from 'next/link';
import { use } from 'react';
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
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import { UserSessionsTable } from '../_components';
import { useUserForm } from '../_hooks';
import { useDisableUser, useUser } from '../users.queries';
import type { UserFormValues } from '../users.types';

interface UserPageProps {
  readonly params: Promise<{ readonly id: string }>;
}

function DisableUserButton({ id, isActive }: { readonly id: Id; readonly isActive: boolean }) {
  const disableUser = useDisableUser(id);
  const { reportSuccess, reportFailure } = useMutationFeedback();

  if (!isActive) return <Tag color="error">Вимкнений</Tag>;

  return (
    <PermissionGate resource="users" action="disable" fallback={null}>
      <DeleteConfirm
        title="Вимкнути користувача?"
        description="Він більше не зможе увійти, але всі його записи лишаються."
        isPending={disableUser.isPending}
        onConfirm={() =>
          disableUser.mutate(undefined, {
            onSuccess: () => reportSuccess('Користувача вимкнено'),
            onError: reportFailure,
          })
        }
      >
        <Button danger>Вимкнути</Button>
      </DeleteConfirm>
    </PermissionGate>
  );
}

function UserCard({ id }: { readonly id: Id }) {
  const user = useUser(id);
  const canUpdate = useHasPermission('users', 'update');
  const { form, fields, isSaving, submit } = useUserForm({ user: user.data });

  if (user.isLoading) return <FormPageSkeleton fields={4} />;

  if (user.isError) {
    const status = user.error instanceof ApiError ? user.error.status : 0;
    return (
      <Result
        status={status === 403 ? '403' : '404'}
        title={status === 403 ? 'Недостатньо прав' : 'Користувача не знайдено'}
        subTitle={
          status === 403
            ? 'Ваша роль не має доступу до цього облікового запису.'
            : 'Можливо, запис видалено або посилання застаріло.'
        }
        extra={
          <Link href="/users">
            <Button type="primary">До списку</Button>
          </Link>
        }
      />
    );
  }

  const record = user.data;
  if (!record) return null;

  return (
    <>
      <PageHeader title={record.name} description={record.email} />

      <div className="flex flex-col gap-4">
        <FormCard
          title="Обліковий запис"
          isSaving={isSaving}
          backHref="/users"
          extra={<DisableUserButton id={id} isActive={record.isActive} />}
          {...(canUpdate ? { onSubmit: submit } : {})}
        >
          <Form<UserFormValues>
            form={form}
            layout="vertical"
            requiredMark
            disabled={!canUpdate}
            onFinish={submit}
          >
            {fields}
          </Form>

          <Descriptions size="small" column={1} className="mt-2">
            <Descriptions.Item label="Ідентифікатор">
              <CopyableValue value={record.id} />
            </Descriptions.Item>
            <Descriptions.Item label="Створено">
              <DateValue value={record.createdAt} withTime />
            </Descriptions.Item>
            <Descriptions.Item label="Оновлено">
              <DateValue value={record.updatedAt} withTime />
            </Descriptions.Item>
          </Descriptions>
        </FormCard>

        <Card title="Сесії" size="small">
          <UserSessionsTable userId={id} canRevoke={canUpdate} />
        </Card>
      </div>
    </>
  );
}

export default function UserPage({ params }: UserPageProps) {
  const { id } = use(params);

  return (
    <PermissionGate resource="users" action="read">
      <UserCard id={id} />
    </PermissionGate>
  );
}
