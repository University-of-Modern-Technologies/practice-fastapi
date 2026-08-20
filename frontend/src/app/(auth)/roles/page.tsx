'use client';

import { Alert, Button, Card, Col, List, Row, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { EmptyState, PageHeader, PermissionGate, TablePageSkeleton } from '@/components';
import { useHasPermission, useMutationFeedback, useReportError } from '@/shared/hooks';
import { CreateRoleModal, PermissionMatrix } from './_components';
import { useReplaceRolePermissions, useRoles } from './roles.queries';
import type { PermissionGrant, Role } from './roles.types';

interface RoleEditorProps {
  readonly role: Role;
  readonly canEdit: boolean;
}

/**
 * Mounted with the role id as its key, so switching roles starts from the saved
 * set instead of carrying another role's unsaved edits across.
 */
function RoleEditor({ role, canEdit }: RoleEditorProps) {
  const [draft, setDraft] = useState<readonly PermissionGrant[]>(role.permissions);
  const save = useReplaceRolePermissions(role.id);
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const submit = (): void => {
    save.mutate(draft, {
      onSuccess: () => reportSuccess('Дозволи ролі збережено'),
      onError: reportFailure,
    });
  };

  return (
    <Card
      title={role.name}
      extra={
        canEdit ? (
          <Button type="primary" loading={save.isPending} onClick={submit}>
            Зберегти дозволи
          </Button>
        ) : null
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {role.description ? (
          <Typography.Text type="secondary">{role.description}</Typography.Text>
        ) : null}

        <Alert
          type="warning"
          showIcon
          message="Збереження замінює весь набір дозволів ролі"
          description="Надсилається саме те, що показано в матриці: знятий дозвіл зникає у ролі, а не лишається від попереднього набору."
        />

        <PermissionMatrix value={draft} onChange={setDraft} disabled={!canEdit} />
      </Space>
    </Card>
  );
}

function RolesBoard() {
  const roles = useRoles();
  const canEdit = useHasPermission('users', 'update');
  const canCreate = useHasPermission('users', 'create');
  const reportError = useReportError();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const { isError, error } = roles;
  useEffect(() => {
    if (isError) reportError(error);
  }, [isError, error, reportError]);

  const items = roles.data ?? [];
  const selected = items.find((role) => role.id === selectedId) ?? items[0];

  if (roles.isLoading) return <TablePageSkeleton rows={6} />;

  return (
    <>
      <PageHeader
        title="Доступи"
        description="Ролі та матриця дозволів «ресурс — дія — область»"
        actions={
          canCreate ? (
            <Button type="primary" onClick={() => setIsCreating(true)}>
              Створити роль
            </Button>
          ) : null
        }
      />

      {items.length === 0 ? (
        <Card>
          <EmptyState description="Ролей ще немає" />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={7} xl={6}>
            <Card size="small" title="Ролі">
              <List
                size="small"
                dataSource={items as Role[]}
                renderItem={(role) => (
                  <List.Item
                    onClick={() => setSelectedId(role.id)}
                    style={{
                      cursor: 'pointer',
                      background:
                        role.id === selected?.id ? 'var(--crm-color-primary-bg)' : undefined,
                    }}
                  >
                    <List.Item.Meta
                      title={role.name}
                      description={`${role.permissions.length} дозволів`}
                    />
                    {role.id === selected?.id ? <Tag color="processing">Обрано</Tag> : null}
                  </List.Item>
                )}
              />
            </Card>
          </Col>

          <Col xs={24} lg={17} xl={18}>
            {selected ? (
              <RoleEditor key={selected.id} role={selected} canEdit={canEdit} />
            ) : (
              <Card>
                <EmptyState description="Оберіть роль зліва" />
              </Card>
            )}
          </Col>
        </Row>
      )}

      <CreateRoleModal
        open={isCreating}
        onClose={() => setIsCreating(false)}
        onCreated={(role) => setSelectedId(role.id)}
      />
    </>
  );
}

export default function RolesPage() {
  // Reading roles is guarded by `users:read`, the same permission as the list.
  return (
    <PermissionGate resource="users" action="read">
      <RolesBoard />
    </PermissionGate>
  );
}
