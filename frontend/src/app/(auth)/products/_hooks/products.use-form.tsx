'use client';

import { Col, Form, Input, Row, Switch, type FormInstance } from 'antd';
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { ConflictAlert, applyServerErrors, zodRule } from '@/components';
import { DEFAULT_CURRENCY, Money } from '@/lib/money';
import { ApiError } from '@/shared/api';
import { useMutationFeedback, useUnsavedChanges, useVersionConflict } from '@/shared/hooks';
import { useCreateProduct, useUpdateProduct } from '../products.queries';
import {
  PRODUCT_ERROR,
  type CreateProductInput,
  type Product,
  type UpdateProductInput,
} from '../products.types';
import {
  productCategorySchema,
  productCurrencySchema,
  productDescriptionSchema,
  productNameSchema,
  productPriceSchema,
  productSkuSchema,
  type ProductFormValues,
} from '../products.validation';

interface UseProductFormOptions {
  /** Absent on the create route; present, and the form edits that record. */
  readonly product?: Product | undefined;
  readonly onSaved: (product: Product) => void;
  /** Re-reads the record after a lost race, so the next save carries the current version. */
  readonly onReload?: (() => unknown) | undefined;
  readonly isReloading?: boolean | undefined;
}

interface UseProductFormResult {
  readonly formProps: {
    readonly form: FormInstance<ProductFormValues>;
    readonly initialValues: Partial<ProductFormValues>;
    readonly layout: 'vertical';
    readonly requiredMark: boolean;
    readonly onValuesChange: () => void;
    readonly onFinish: () => void;
  };
  readonly fields: ReactNode;
  readonly conflictAlert: ReactNode;
  readonly submit: () => void;
  readonly isSaving: boolean;
  /** Routes a failed write to the field it belongs to; also used by the delete action. */
  readonly handleError: (error: unknown) => void;
}

const asText = (value: string | undefined): string => (value ?? '').trim();

/**
 * The one form behind both product routes. Create and edit differ in exactly
 * two places — the SKU is fixed after creation, and an update carries the
 * version it read — so splitting them into two components would duplicate every
 * field to express that.
 */
export const useProductForm = ({
  product,
  onSaved,
  onReload,
  isReloading = false,
}: UseProductFormOptions): UseProductFormResult => {
  const [form] = Form.useForm<ProductFormValues>();
  const [isDirty, setIsDirty] = useState(false);
  const { reportSuccess, reportFailure } = useMutationFeedback();
  const { hasConflict, handleError: handleConflict, clearConflict } = useVersionConflict();

  const isEdit = product !== undefined;
  const create = useCreateProduct();
  const update = useUpdateProduct(product?.id ?? '');

  useUnsavedChanges(isDirty);

  const initialValues = useMemo<Partial<ProductFormValues>>(
    () =>
      product
        ? {
            sku: product.sku,
            name: product.name,
            // The stored amount is normalised through Money, so the field shows
            // the same scale the API keeps rather than whatever it was typed as.
            unitPrice: Money.parse(product.unitPrice, product.currency).toWire(),
            currency: product.currency,
            isActive: product.isActive,
            ...(product.description === null ? {} : { description: product.description }),
            ...(product.category === null ? {} : { category: product.category }),
          }
        : { currency: DEFAULT_CURRENCY, isActive: true },
    [product],
  );

  const handleError = useCallback(
    (error: unknown) => {
      if (handleConflict(error)) return;

      // A taken SKU belongs on the field that caused it, not in a corner toast:
      // the user has to change that one value and nothing else.
      if (error instanceof ApiError && error.code === PRODUCT_ERROR.skuTaken) {
        form.setFields([{ name: 'sku', errors: ['Товар із таким артикулом уже існує'] }]);
        return;
      }

      if (applyServerErrors(form, error)) return;
      reportFailure(error);
    },
    [form, handleConflict, reportFailure],
  );

  const handleSaved = useCallback(
    (saved: Product, text: string) => {
      setIsDirty(false);
      clearConflict();
      reportSuccess(text);
      onSaved(saved);
    },
    [clearConflict, onSaved, reportSuccess],
  );

  const submit = useCallback(() => {
    void form
      .validateFields()
      .then((values) => {
        const currency = values.currency.trim().toUpperCase();
        const unitPrice = Money.fromInput(values.unitPrice, currency).toWire();
        const description = asText(values.description);
        const category = asText(values.category);

        if (product) {
          const input: UpdateProductInput = {
            // The version read with the record; a stale one answers 409.
            version: product.version,
            name: values.name.trim(),
            description: description === '' ? null : description,
            category: category === '' ? null : category,
            unitPrice,
            currency,
            isActive: values.isActive,
          };

          update.mutate(input, {
            onSuccess: (saved) => handleSaved(saved, 'Товар збережено'),
            onError: handleError,
          });
          return;
        }

        const input: CreateProductInput = {
          sku: values.sku.trim().toUpperCase(),
          name: values.name.trim(),
          unitPrice,
          currency,
          isActive: values.isActive,
          ...(description === '' ? {} : { description }),
          ...(category === '' ? {} : { category }),
        };

        create.mutate(input, {
          onSuccess: (saved) => handleSaved(saved, 'Товар створено'),
          onError: handleError,
        });
      })
      // A form that failed its own rules has already marked the offending
      // fields; there is nothing further to report.
      .catch(() => undefined);
  }, [create, form, handleError, handleSaved, product, update]);

  const reload = useCallback(() => {
    void Promise.resolve(onReload?.()).finally(() => clearConflict());
  }, [clearConflict, onReload]);

  const fields = (
    <>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item
            name="sku"
            label="Артикул"
            rules={[zodRule(productSkuSchema)]}
            extra={
              isEdit ? 'Артикул не змінюється після створення' : 'Зберігається у верхньому регістрі'
            }
          >
            <Input disabled={isEdit} autoFocus={!isEdit} placeholder="SKU-001" />
          </Form.Item>
        </Col>

        <Col xs={24} md={16}>
          <Form.Item name="name" label="Назва" rules={[zodRule(productNameSchema)]}>
            <Input autoFocus={isEdit} placeholder="Назва товару" maxLength={160} />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item name="category" label="Категорія" rules={[zodRule(productCategorySchema)]}>
            <Input allowClear placeholder="Наприклад, обладнання" maxLength={80} />
          </Form.Item>
        </Col>

        <Col xs={12} md={8}>
          <Form.Item name="unitPrice" label="Ціна" rules={[zodRule(productPriceSchema)]}>
            <Input className="numeric" inputMode="decimal" placeholder="1200.00" />
          </Form.Item>
        </Col>

        <Col xs={12} md={8}>
          <Form.Item name="currency" label="Валюта" rules={[zodRule(productCurrencySchema)]}>
            <Input maxLength={3} placeholder={DEFAULT_CURRENCY} />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name="description" label="Опис" rules={[zodRule(productDescriptionSchema)]}>
        <Input.TextArea rows={4} maxLength={4000} showCount placeholder="Необовʼязково" />
      </Form.Item>

      <Form.Item name="isActive" label="Доступний до продажу" valuePropName="checked">
        <Switch checkedChildren="Активний" unCheckedChildren="Вимкнено" />
      </Form.Item>
    </>
  );

  return {
    formProps: {
      form,
      initialValues,
      layout: 'vertical',
      requiredMark: false,
      onValuesChange: () => setIsDirty(true),
      onFinish: submit,
    },
    fields,
    conflictAlert: <ConflictAlert open={hasConflict} onReload={reload} isReloading={isReloading} />,
    submit,
    isSaving: create.isPending || update.isPending,
    handleError,
  };
};
