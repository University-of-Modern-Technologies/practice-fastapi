'use client';

import { Button, Result } from 'antd';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams, usePermissionScope, useReportError } from '@/shared/hooks';
import { useAuthStore } from '@/shared/stores';
import { useUsersTableColumns } from './_hooks';
import { useUsers } from './users.queries';

/**
 * `users:read` with scope `OWN` does not open the list — the API answers 403 —
 * so the section says why instead of showing a table that will never fill.
 */
function OwnScopeNotice() {
  const ownId = useAuthStore((state) => state.user?.id);

  return (
    <Result
      status="info"
      title="Список користувачів недоступний"
      subTitle="Ваша роль бачить лише власний обліковий запис. Перегляд усіх користувачів потребує області «Усі записи»."
      {...(ownId
        ? {
            extra: (
              <Link href={`/users/${ownId}`}>
                <Button type="primary">Мій профіль</Button>
              </Link>
            ),
          }
        : {})}
    />
  );
}

function UsersList() {
  const router = useRouter();
  const scope = usePermissionScope('users', 'read');
  const columns = useUsersTableColumns();
  const reportError = useReportError();

  const { params, setParams } = useListParams({ defaults: { page: 1, pageSize: 20 } });
  const users = useUsers({ page: params.page, pageSize: params.pageSize }, scope === 'ALL');

  const { isError, error } = users;
  useEffect(() => {
    if (isError) reportError(error);
  }, [isError, error, reportError]);

  return (
    <>
      <PageHeader
        title="Користувачі"
        description="Облікові записи, їхні ролі та активні сесії"
        actions={
          <PermissionGate resource="users" action="create" fallback={null}>
            <Link href="/users/new">
              <Button type="primary">Створити користувача</Button>
            </Link>
          </PermissionGate>
        }
      />

      {scope === 'ALL' ? (
        <DataTable
          tableId="users"
          columns={columns}
          page={users.data}
          isLoading={users.isLoading}
          params={params}
          onParamsChange={setParams}
          onRowClick={(user) => router.push(`/users/${user.id}`)}
          emptyText="Користувачів ще немає"
        />
      ) : (
        <OwnScopeNotice />
      )}
    </>
  );
}

export default function UsersPage() {
  return (
    <PermissionGate resource="users" action="read">
      <UsersList />
    </PermissionGate>
  );
}
