'use client';

import { Col, Form, Input, Row, Switch, type FormInstance } from 'antd';
import { useCallback, useMemo, type ReactNode } from 'react';
import { ConflictAlert, applyServerErrors, zodRule } from '@/components';
import { Money } from '@/lib/money';
import { ApiError } from '@/shared/api';
import { useMutationFeedback, useRecordForm } from '@/shared/hooks';
import { useCreateProduct, useUpdateProduct } from '../products.queries';
import {
  PRODUCT_ERROR,
  PRODUCT_ERROR_MESSAGES,
  type CreateProductInput,
  type Product,
  type UpdateProductInput,
} from '../products.types';
import {
  productCategorySchema,
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
  /** Re-reads the record after a lost race; the form then shows it with its version. */
  readonly onReload?:
    | (() => Promise<{ readonly data?: Product | undefined; readonly isError?: boolean }>)
    | undefined;
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
 * A product as the form shows it. Every field is named, absent ones included,
 * so a re-read clears a value the other person removed instead of keeping ours.
 */
const toProductValues = (product: Product): Partial<ProductFormValues> => ({
  sku: product.sku,
  name: product.name,
  // The stored amount is normalised through Money, so the field shows the same
  // scale the API keeps rather than whatever it was typed as.
  unitPrice: Money.parse(product.unitPrice, product.currency).toWire(),
  currency: product.currency,
  isActive: product.isActive,
  description: product.description ?? undefined,
  category: product.category ?? undefined,
});

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
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  // `base` is the copy on screen: its values are in the fields and its version
  // is the one a save sends, even after a fresher copy reached the cache.
  const { base, markDirty, adopt, hasConflict, handleConflict, reload } = useRecordForm({
    form,
    record: product,
    toValues: toProductValues,
    onReload,
  });

  const isEdit = product !== undefined;
  const create = useCreateProduct();
  const update = useUpdateProduct(product?.id ?? '');

  // Read once, at mount; every later copy reaches the fields through the hook.
  const initialValues = useMemo<Partial<ProductFormValues>>(
    () => (base ? toProductValues(base) : { isActive: true }),
    [base],
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
      reportFailureWith(PRODUCT_ERROR_MESSAGES)(error);
    },
    [form, handleConflict, reportFailureWith],
  );

  const handleSaved = useCallback(
    (saved: Product, text: string) => {
      adopt(saved);
      reportSuccess(text);
      onSaved(saved);
    },
    [adopt, onSaved, reportSuccess],
  );

  const submit = useCallback(() => {
    void form
      .validateFields()
      .then((values) => {
        // No currency on either route: the catalogue is kept in the
        // organisation's one, which the API fills in on create, and an update
        // that echoed it back would be refused for an older product in another.
        const unitPrice = Money.fromInput(values.unitPrice).toWire();
        const description = asText(values.description);
        const category = asText(values.category);

        if (base) {
          const input: UpdateProductInput = {
            // The version of the copy the user edited; a stale one answers 409.
            version: base.version,
            name: values.name.trim(),
            description: description === '' ? null : description,
            category: category === '' ? null : category,
            unitPrice,
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
  }, [base, create, form, handleError, handleSaved, update]);

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
          <Form.Item
            name="currency"
            label="Валюта"
            extra={isEdit ? undefined : 'Валюта організації, задається в налаштуваннях'}
          >
            <Input disabled placeholder="Валюта організації" />
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
      onValuesChange: markDirty,
      onFinish: submit,
    },
    fields,
    conflictAlert: <ConflictAlert open={hasConflict} onReload={reload} isReloading={isReloading} />,
    submit,
    isSaving: create.isPending || update.isPending,
    handleError,
  };
};
