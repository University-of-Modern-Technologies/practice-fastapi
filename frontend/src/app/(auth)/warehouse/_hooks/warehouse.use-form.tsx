'use client';

import { Form, type FormInstance } from 'antd';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { applyServerErrors } from '@/components';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { useCreateWarehouse, useUpdateWarehouse } from '../warehouse.queries';
import type { Warehouse } from '../warehouse.types';
import type { WarehouseFormValues } from '../warehouse.validation';

const CODE_ERRORS: Readonly<Record<string, string>> = {
  WAREHOUSE_CODE_TAKEN: 'Склад із таким кодом уже існує',
  WAREHOUSE_CODE_IMMUTABLE: 'Код складу змінити не можна',
};

interface UseWarehouseFormResult {
  readonly form: FormInstance<WarehouseFormValues>;
  readonly submit: () => void;
  readonly isSaving: boolean;
  readonly isEditing: boolean;
}

/**
 * Shared by the create page and the card. Both send the same fields; the only
 * difference is that an existing warehouse keeps its code, which the API
 * refuses to change, so the update never carries it.
 */
export const useWarehouseForm = (warehouse?: Warehouse): UseWarehouseFormResult => {
  const router = useRouter();
  const [form] = Form.useForm<WarehouseFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const create = useCreateWarehouse();
  const update = useUpdateWarehouse(warehouse?.id ?? '');
  const isEditing = warehouse !== undefined;

  useEffect(() => {
    if (!warehouse) return;
    form.setFieldsValue({
      code: warehouse.code,
      name: warehouse.name,
      isActive: warehouse.isActive,
    });
  }, [warehouse, form]);

  const handleFailure = (error: unknown): void => {
    // A taken code belongs on the code field, not in a corner notification.
    const codeError = error instanceof ApiError ? CODE_ERRORS[error.code] : undefined;
    if (codeError) {
      form.setFields([{ name: 'code', errors: [codeError] }]);
      return;
    }
    if (applyServerErrors(form, error)) return;
    reportFailure(error);
  };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        if (warehouse) {
          update.mutate(
            { name: values.name, isActive: values.isActive },
            {
              onSuccess: () => reportSuccess('Склад збережено'),
              onError: handleFailure,
            },
          );
          return;
        }

        create.mutate(
          { code: values.code.toUpperCase(), name: values.name, isActive: values.isActive },
          {
            onSuccess: (created) => {
              reportSuccess('Склад створено');
              router.replace(`/warehouse/${created.id}`);
            },
            onError: handleFailure,
          },
        );
      })
      // A failed field validation already shows itself under the inputs.
      .catch(() => undefined);
  };

  return { form, submit, isSaving: create.isPending || update.isPending, isEditing };
};
