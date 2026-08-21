'use client';

import { App, Checkbox, Form, Input, InputNumber, Select } from 'antd';
import { useEffect } from 'react';
import { FormModal, ReferenceSelect, applyServerErrors, renderSelectNotice } from '@/components';
import {
  productLabel,
  useProductOptions,
  useResolvedProduct,
} from '@/app/(auth)/products/products.queries';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import { describeStockError, useStockOperation } from '../stock.queries';
import { useWarehouseOptions } from '../warehouse.queries';
import {
  STOCK_OPERATION_LABEL,
  STOCK_OPERATIONS,
  type StockOperation,
  type StockOperationRequest,
} from '../warehouse.types';
import { blankToUndefined, showsField, stockOperationSchema } from '../warehouse.validation';

interface OperationFormValues {
  operation: StockOperation;
  warehouseId: string;
  productId: string;
  quantity?: number | null;
  delta?: number | null;
  fromReservation?: boolean;
  referenceType?: string;
  referenceId?: string;
  note?: string;
}

interface StockOperationModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  /** Pre-selects the row the user started from, when there is one. */
  readonly defaultWarehouseId?: string | undefined;
  readonly defaultProductId?: string | undefined;
}

const OPERATION_OPTIONS = STOCK_OPERATIONS.map((operation) => ({
  value: operation,
  label: STOCK_OPERATION_LABEL[operation],
}));

const HINTS: Readonly<Record<StockOperation, string>> = {
  receive: 'Збільшує кількість на руках.',
  issue: 'Зменшує кількість на руках; за потреби списує з наявного резерву.',
  reserve: 'Переносить кількість із доступної в резерв під конкретну підставу.',
  release: 'Повертає зарезервовану кількість у доступну.',
  adjust: 'Виправляє кількість на руках у будь-який бік; коментар обовʼязковий.',
};

/**
 * One dialog for all five stock operations. They differ by three fields, not by
 * layout: splitting them into five modals would duplicate the target picker,
 * the reference pair and the error handling five times over.
 */
export function StockOperationModal({
  open,
  onClose,
  defaultWarehouseId,
  defaultProductId,
}: StockOperationModalProps) {
  const [form] = Form.useForm<OperationFormValues>();
  const { message } = App.useApp();
  const { reportSuccess, reportFailure } = useMutationFeedback();
  const { options, isLoading, notice } = useWarehouseOptions();
  const operate = useStockOperation();

  // Reading the catalogue is a permission of its own: without it the picker is
  // not mounted, so the dialog never fires a request the API would refuse.
  const canReadProducts = useHasPermission('products', 'read');

  const operation = (Form.useWatch('operation', form) ?? 'receive') as StockOperation;
  const fromReservation = Form.useWatch('fromReservation', form) === true;

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      operation: 'receive',
      warehouseId: defaultWarehouseId ?? '',
      productId: defaultProductId ?? '',
    });
  }, [open, defaultWarehouseId, defaultProductId, form]);

  // A reserve or release is always held on behalf of something, and an issue
  // taken out of a reservation has to name the one it consumes.
  const referenceRequired =
    operation === 'reserve' ||
    operation === 'release' ||
    (operation === 'issue' && fromReservation);

  const handleFailure = (error: unknown): void => {
    const known = describeStockError(error);
    if (known) {
      void message.error(known);
      return;
    }
    if (applyServerErrors(form, error)) return;
    reportFailure(error);
  };

  const buildRequest = (values: OperationFormValues): StockOperationRequest => {
    const target = { warehouseId: values.warehouseId, productId: values.productId };
    const referenceType = blankToUndefined(values.referenceType);
    const referenceId = blankToUndefined(values.referenceId);
    const note = blankToUndefined(values.note);
    const quantity = Number(values.quantity);

    switch (values.operation) {
      case 'adjust':
        return {
          operation: 'adjust',
          input: {
            ...target,
            delta: Number(values.delta),
            note: note ?? '',
            referenceType,
            referenceId,
          },
        };
      case 'reserve':
      case 'release':
        return {
          operation: values.operation,
          input: {
            ...target,
            quantity,
            referenceType: referenceType ?? '',
            referenceId: referenceId ?? '',
            note,
          },
        };
      case 'issue':
        return {
          operation: 'issue',
          input: {
            ...target,
            quantity,
            fromReservation: values.fromReservation === true,
            referenceType,
            referenceId,
            note,
          },
        };
      default:
        return {
          operation: 'receive',
          input: { ...target, quantity, referenceType, referenceId, note },
        };
    }
  };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        const request = buildRequest(values);

        // The whole body is checked before it leaves: a cross-field rule such as
        // "an issue from a reservation needs a reference" has no single field to
        // hang off, so antd's per-field rules cannot express it.
        const parsed = stockOperationSchema(request.operation).safeParse(request.input);
        if (!parsed.success) {
          form.setFields(
            parsed.error.issues.map((issue) => ({
              name: (issue.path[0] ?? 'productId') as keyof OperationFormValues,
              errors: [issue.message],
            })),
          );
          return;
        }

        operate.mutate(request, {
          onSuccess: () => {
            reportSuccess(`${STOCK_OPERATION_LABEL[request.operation]}: операцію виконано`);
            form.resetFields();
            onClose();
          },
          onError: handleFailure,
        });
      })
      .catch(() => undefined);
  };

  return (
    <FormModal
      open={open}
      title="Операція зі складом"
      submitLabel="Виконати"
      isSaving={operate.isPending}
      onSubmit={submit}
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
    >
      <Form<OperationFormValues>
        form={form}
        layout="vertical"
        requiredMark
        initialValues={{ operation: 'receive' }}
      >
        <Form.Item name="operation" label="Операція" extra={HINTS[operation]}>
          <Select options={OPERATION_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="warehouseId"
          label="Склад"
          rules={[{ required: true, message: 'Оберіть склад' }]}
        >
          <Select
            options={options as { value: string; label: string }[]}
            loading={isLoading}
            showSearch
            optionFilterProp="label"
            placeholder="Оберіть склад"
            popupRender={(menu) => renderSelectNotice(menu, notice)}
          />
        </Form.Item>

        <Form.Item
          name="productId"
          label="Товар"
          rules={[{ required: true, message: 'Вкажіть товар' }]}
          extra={canReadProducts ? undefined : 'Немає доступу до каталогу — вкажіть ідентифікатор'}
        >
          {canReadProducts ? (
            <ReferenceSelect
              useOptions={useProductOptions}
              useResolved={useResolvedProduct}
              getLabel={productLabel}
              placeholder="Почніть вводити назву або артикул"
              notFoundText="Товарів не знайдено"
            />
          ) : (
            <Input placeholder="00000000-0000-0000-0000-000000000000" />
          )}
        </Form.Item>

        {showsField(operation, 'quantity') ? (
          <Form.Item
            name="quantity"
            label="Кількість"
            rules={[{ required: true, message: 'Вкажіть кількість' }]}
          >
            <InputNumber min={1} step={1} style={{ width: '100%' }} />
          </Form.Item>
        ) : null}

        {showsField(operation, 'delta') ? (
          <Form.Item
            name="delta"
            label="Коригування"
            extra="Відʼємне значення зменшує кількість на руках."
            rules={[{ required: true, message: 'Вкажіть коригування' }]}
          >
            <InputNumber step={1} style={{ width: '100%' }} />
          </Form.Item>
        ) : null}

        {showsField(operation, 'fromReservation') ? (
          <Form.Item name="fromReservation" valuePropName="checked">
            <Checkbox>Списати з резерву</Checkbox>
          </Form.Item>
        ) : null}

        <Form.Item
          name="referenceType"
          label="Тип підстави"
          rules={referenceRequired ? [{ required: true, message: 'Вкажіть тип підстави' }] : []}
        >
          <Input placeholder="order" />
        </Form.Item>

        <Form.Item
          name="referenceId"
          label="Ідентифікатор підстави"
          rules={referenceRequired ? [{ required: true, message: 'Вкажіть підставу' }] : []}
        >
          <Input placeholder="00000000-0000-0000-0000-000000000000" />
        </Form.Item>

        <Form.Item
          name="note"
          label="Коментар"
          rules={
            operation === 'adjust'
              ? [{ required: true, message: 'Вкажіть причину коригування' }]
              : []
          }
        >
          <Input.TextArea rows={2} maxLength={255} />
        </Form.Item>
      </Form>
    </FormModal>
  );
}
