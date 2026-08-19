'use client';

import { Form, Input, Select, Typography } from 'antd';
import { useEffect, useMemo, type ReactNode } from 'react';
import { applyServerErrors, requiredRule, zodRule } from '@/components';
import { useRoles } from '@/app/(auth)/roles/roles.queries';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { ERROR_CODE, type Id } from '@/types/domain';
import { useCreateUser, useUpdateUser } from '../users.queries';
import type { User, UserFormValues } from '../users.types';
import {
  userEmailSchema,
  userNameSchema,
  userPasswordSchema,
  userRoleIdsSchema,
} from '../users.validation';

interface UseUserFormOptions {
  /** Present in edit mode; its absence means the form creates an account. */
  readonly user?: User | undefined;
  readonly onSaved?: (user: User) => void;
}

interface UseUserForm {
  readonly form: ReturnType<typeof Form.useForm<UserFormValues>>[0];
  readonly fields: ReactNode;
  readonly isSaving: boolean;
  readonly submit: () => void;
}

const EMPTY_ID = '' as Id;

/**
 * Holds everything the create page and the card page share: the same fields,
 * the same rules, and the same handling of a rejected save. Only the password
 * behaves differently between the two, and that difference lives here as well.
 */
export const useUserForm = ({ user, onSaved }: UseUserFormOptions = {}): UseUserForm => {
  const [form] = Form.useForm<UserFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const roles = useRoles();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser(user?.id ?? EMPTY_ID);

  useEffect(() => {
    if (!user) return;
    form.setFieldsValue({
      email: user.email,
      name: user.name,
      roleIds: user.roles.map((role) => role.id),
    });
  }, [user, form]);

  const roleOptions = useMemo(
    () => (roles.data ?? []).map((role) => ({ value: role.id, label: role.name })),
    [roles.data],
  );

  const reportSaveFailure = (error: unknown): void => {
    if (applyServerErrors(form, error)) return;

    // A taken address is the one failure the user can fix on the spot, so it
    // belongs on the field rather than in a notification they have to remember.
    if (error instanceof ApiError && error.code === ERROR_CODE.emailAlreadyExists) {
      form.setFields([{ name: 'email', errors: ['Ця пошта вже зайнята'] }]);
      return;
    }

    reportFailure(error);
  };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        const password = values.password?.trim();

        if (user) {
          return updateUser
            .mutateAsync({
              email: values.email,
              name: values.name,
              roleIds: values.roleIds,
              // An untouched password field must not reset the account's password.
              ...(password ? { password } : {}),
            })
            .then((saved) => {
              form.setFieldValue('password', undefined);
              reportSuccess('Зміни збережено');
              onSaved?.(saved);
            });
        }

        return createUser
          .mutateAsync({
            email: values.email,
            name: values.name,
            password: password ?? '',
            roleIds: values.roleIds,
          })
          .then((saved) => {
            reportSuccess('Користувача створено');
            onSaved?.(saved);
          });
      })
      .catch((error: unknown) => {
        // A failed field validation resolves inside antd and needs no report.
        if (error instanceof Error) reportSaveFailure(error);
      });
  };

  const fields = (
    <>
      <Form.Item name="email" label="Пошта" rules={[requiredRule(), zodRule(userEmailSchema)]}>
        <Input autoComplete="off" placeholder="user@example.com" />
      </Form.Item>

      <Form.Item name="name" label="Імʼя" rules={[requiredRule(), zodRule(userNameSchema)]}>
        <Input autoComplete="off" placeholder="Прізвище та імʼя" />
      </Form.Item>

      <Form.Item
        name="password"
        label={user ? 'Новий пароль' : 'Пароль'}
        rules={
          user
            ? [
                {
                  validator: (_rule, value: string | undefined) =>
                    !value || userPasswordSchema.safeParse(value).success
                      ? Promise.resolve()
                      : Promise.reject(new Error('Від 8 до 128 символів')),
                },
              ]
            : [requiredRule(), zodRule(userPasswordSchema)]
        }
        extra={user ? 'Залиште порожнім, щоб не змінювати пароль' : undefined}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>

      <Form.Item name="roleIds" label="Ролі" rules={[zodRule(userRoleIdsSchema)]}>
        <Select
          mode="multiple"
          allowClear
          loading={roles.isLoading}
          options={roleOptions}
          placeholder="Оберіть ролі"
          notFoundContent={roles.isLoading ? null : <Typography.Text>Ролей немає</Typography.Text>}
        />
      </Form.Item>
    </>
  );

  return {
    form,
    fields,
    isSaving: createUser.isPending || updateUser.isPending,
    submit,
  };
};
