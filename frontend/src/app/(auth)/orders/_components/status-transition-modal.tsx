'use client';

import { Alert, Form, Radio, Space } from 'antd';
import { FormModal, StatusTag } from '@/components';
import { ORDER_STATUS, ORDER_STATUS_TRANSITIONS, type OrderStatus } from '@/shared/constants';
import { useMutationFeedback } from '@/shared/hooks';
import { useTransitionOrder } from '../orders.queries';
import { ORDER_ERROR_MESSAGES, type Order } from '../orders.types';

interface TransitionFormValues {
  status: OrderStatus;
}

interface StatusTransitionModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly order: Order;
  /** Lets the card show the conflict alert; returns true when it took over. */
  readonly onConflict?: ((error: unknown) => boolean) | undefined;
}

const CONSEQUENCES: Readonly<Partial<Record<OrderStatus, string>>> = {
  CONFIRMED:
    'Підтвердження зарезервує залишок кожної позиції на складі за замовчуванням. ' +
    'Якщо доступного залишку не вистачить, перехід буде відхилено.',
  CANCELLED: 'Скасування знімає раніше створені резерви. Повернути статус назад не можна.',
  FULFILLED: 'Виконання списує зарезервований залишок. Це кінцевий статус.',
};

/**
 * Offers only the moves the state machine allows, so an impossible transition
 * is never proposed — the 409 the server would answer with stays a safety net
 * rather than the primary check.
 */
export function StatusTransitionModal({
  open,
  onClose,
  order,
  onConflict,
}: StatusTransitionModalProps) {
  const [form] = Form.useForm<TransitionFormValues>();
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const transition = useTransitionOrder(order.id);

  const allowed = ORDER_STATUS_TRANSITIONS[order.status];
  const target = (Form.useWatch('status', form) ?? allowed[0]) as OrderStatus | undefined;
  const isEmpty = order.items.length === 0;

  const close = (): void => {
    form.resetFields();
    onClose();
  };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        transition.mutate(
          // The version read with the card travels with the move as well.
          { version: order.version, status: values.status },
          {
            onSuccess: (updated) => {
              reportSuccess(`Статус змінено: ${ORDER_STATUS[updated.status].label}`);
              close();
            },
            onError: (error) => {
              if (onConflict?.(error) === true) {
                close();
                return;
              }
              reportFailureWith(ORDER_ERROR_MESSAGES)(error);
            },
          },
        );
      })
      .catch(() => undefined);
  };

  return (
    <FormModal
      open={open}
      title="Зміна статусу"
      submitLabel="Змінити статус"
      isSaving={transition.isPending}
      onSubmit={submit}
      onCancel={close}
      danger={target === 'CANCELLED'}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Space size="small">
          <span>Поточний статус:</span>
          <StatusTag dictionary={ORDER_STATUS} value={order.status} />
        </Space>

        {isEmpty ? <Alert type="warning" showIcon message="Додайте хоча б одну позицію" /> : null}

        <Form<TransitionFormValues>
          form={form}
          layout="vertical"
          initialValues={allowed[0] ? { status: allowed[0] } : {}}
        >
          <Form.Item
            name="status"
            label="Новий статус"
            rules={[{ required: true, message: 'Оберіть статус' }]}
          >
            <Radio.Group>
              <Space direction="vertical">
                {allowed.map((status) => (
                  <Radio key={status} value={status}>
                    {ORDER_STATUS[status].label}
                  </Radio>
                ))}
              </Space>
            </Radio.Group>
          </Form.Item>
        </Form>

        {target && CONSEQUENCES[target] ? (
          <Alert type="info" showIcon message={CONSEQUENCES[target]} />
        ) : null}
      </Space>
    </FormModal>
  );
}
