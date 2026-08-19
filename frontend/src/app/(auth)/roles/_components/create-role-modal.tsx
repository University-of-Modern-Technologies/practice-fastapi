'use client';

import { Form, Input, Typography } from 'antd';
import { useState } from 'react';
import { FormModal, applyServerErrors, requiredRule, zodRule } from '@/components';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { useCreateRole } from '../roles.queries';
import type { PermissionGrant, Role, RoleFormValues } from '../roles.types';
import { roleDescriptionSchema, roleNameSchema } from '../roles.validation';
import { PermissionMatrix } from './permission-matrix';

interface CreateRoleModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onCreated?: (role: Role) => void;
}

/** The API answers a duplicate name with this code rather than a field error. */
const ROLE_ALREADY_EXISTS = 'ROLE_ALREADY_EXISTS';

export function CreateRoleModal({ open, onClose, onCreated }: CreateRoleModalProps) {
  const [form] = Form.useForm<RoleFormValues>();
  const [permissions, setPermissions] = useState<readonly PermissionGrant[]>([]);
  const createRole = useCreateRole();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const close = (): void => {
    form.resetFields();
    setPermissions([]);
    onClose();
  };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        const description = values.description?.trim();

        return createRole
          .mutateAsync({
            name: values.name.trim(),
            ...(description ? { description } : {}),
            permissions,
          })
          .then((role) => {
            reportSuccess('Роль створено');
            onCreated?.(role);
            close();
          });
      })
      .catch((error: unknown) => {
        if (!(error instanceof Error)) return;
        if (applyServerErrors(form, error)) return;
        if (error instanceof ApiError && error.code === ROLE_ALREADY_EXISTS) {
          form.setFields([{ name: 'name', errors: ['Роль із такою назвою вже існує'] }]);
          return;
        }
        reportFailure(error);
      });
  };

  return (
    <FormModal
      open={open}
      title="Нова роль"
      isSaving={createRole.isPending}
      onSubmit={submit}
      onCancel={close}
      submitLabel="Створити"
      width={960}
    >
      <Form<RoleFormValues> form={form} layout="vertical" requiredMark>
        <Form.Item name="name" label="Назва" rules={[requiredRule(), zodRule(roleNameSchema)]}>
          <Input autoComplete="off" placeholder="Наприклад, supervisor" />
        </Form.Item>

        <Form.Item name="description" label="Опис" rules={[zodRule(roleDescriptionSchema)]}>
          <Input.TextArea rows={2} placeholder="Для кого ця роль" />
        </Form.Item>
      </Form>

      <Typography.Paragraph type="secondary">
        Дозволи ролі. Їх можна змінити й пізніше — у матриці доступів.
      </Typography.Paragraph>

      <PermissionMatrix value={permissions} onChange={setPermissions} />
    </FormModal>
  );
}
