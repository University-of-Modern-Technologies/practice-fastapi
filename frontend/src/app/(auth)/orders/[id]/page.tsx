'use client';

import { Button, Card, Descriptions, Form, Space } from 'antd';
import { ArrowRightLeft, CopyPlus, Plus, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import {
  BackButton,
  CopyableValue,
  DateValue,
  DeleteConfirm,
  EmptyState,
  FormCard,
  FormPageSkeleton,
  PageHeader,
  PermissionGate,
  ShowMoreText,
  StatusTag,
} from '@/components';
import { ORDER_STATUS, ORDER_STATUS_TRANSITIONS, isOrderEditable } from '@/shared/constants';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import { AddItemModal, OrderItemsTable, OrderTotals, StatusTransitionModal } from '../_components';
import { useOrderForm } from '../_hooks';
import {
  useDeleteOrder,
  useDuplicateOrder,
  useOrder,
  useRemoveOrderItem,
  useUpdateOrderItem,
} from '../orders.queries';
import {
  ORDER_ERROR_MESSAGES,
  isOrderVersionConflict,
  type Order,
  type OrderItemView,
} from '../orders.types';
import type { OrderFormValues } from '../orders.validation';

const toViews = (order: Order): readonly OrderItemView[] =>
  order.items.map((item) => ({
    id: item.id,
    productId: item.productId,
    sku: item.sku,
    name: item.name,
    quantity: item.quantity,
    unitPrice: item.unitPrice,
    lineTotal: item.lineTotal,
  }));

const Meta = ({ order }: { readonly order: Order }) => (
  <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} bordered>
    <Descriptions.Item label="Номер">
      <CopyableValue value={order.orderNumber} />
    </Descriptions.Item>
    <Descriptions.Item label="Ідентифікатор">
      <CopyableValue value={order.id} />
    </Descriptions.Item>
    <Descriptions.Item label="Відповідальний">
      <CopyableValue value={order.ownerId} />
    </Descriptions.Item>
    <Descriptions.Item label="Розміщено">
      <DateValue value={order.placedAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Створено">
      <DateValue value={order.createdAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Оновлено">
      <DateValue value={order.updatedAt} withTime />
    </Descriptions.Item>
  </Descriptions>
);

export default function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const canWrite = useHasPermission('orders', 'write');
  const [isAdding, setIsAdding] = useState(false);
  const [isMoving, setIsMoving] = useState(false);

  const { data: order, isLoading, isError, isFetching, refetch } = useOrder(id);
  const remove = useDeleteOrder(id);
  const duplicate = useDuplicateOrder(id);
  const updateItem = useUpdateOrderItem(id);
  const removeItem = useRemoveOrderItem(id);

  const { formProps, fields, conflictAlert, submit, isSaving, canSubmit, handleError } =
    useOrderForm({
      order,
      // The card stays put after a save: the fresh version arrives through the
      // cache, so there is nowhere to navigate.
      onSaved: () => undefined,
      onReload: refetch,
      isReloading: isFetching,
    });

  /** A lost race gets the alert; everything else gets its own sentence. */
  const handleConflict = (error: unknown): boolean => {
    if (!isOrderVersionConflict(error)) return false;
    handleError(error);
    return true;
  };

  const handleItemError = (error: unknown): void => {
    if (handleConflict(error)) return;
    reportFailureWith(ORDER_ERROR_MESSAGES)(error);
  };

  if (isLoading) return <FormPageSkeleton />;
  if (isError || order === undefined) return <EmptyState description="Замовлення не знайдено" />;

  const isEditable = isOrderEditable(order.status) && canWrite;
  const isItemPending = updateItem.isPending || removeItem.isPending;
  const hasTransitions = ORDER_STATUS_TRANSITIONS[order.status].length > 0;

  const onDelete = () => {
    // The same version the form holds: a delete can lose the race just as a save can.
    remove.mutate(order.version, {
      onSuccess: () => {
        reportSuccess('Замовлення видалено');
        router.replace('/orders');
      },
      onError: handleError,
    });
  };

  const onDuplicate = () => {
    duplicate.mutate(undefined, {
      onSuccess: (copy) => {
        reportSuccess(`Створено замовлення ${copy.orderNumber}`);
        // Straight to the copy: it is a draft that still needs checking, and
        // leaving the operator on the source would hide that a record was made.
        router.push(`/orders/${copy.id}`);
      },
      onError: reportFailureWith(ORDER_ERROR_MESSAGES),
    });
  };

  const duplicateAction = (
    <PermissionGate resource="orders" action="write" fallback={null}>
      <Button icon={<CopyPlus size={16} />} loading={duplicate.isPending} onClick={onDuplicate}>
        Повторити
      </Button>
    </PermissionGate>
  );

  const deleteAction = (
    <PermissionGate resource="orders" action="delete" fallback={null}>
      <DeleteConfirm
        onConfirm={onDelete}
        isPending={remove.isPending}
        title="Видалити замовлення?"
        description="Замовлення буде приховано зі списку."
      >
        <Button danger icon={<Trash2 size={16} />} loading={remove.isPending}>
          Видалити
        </Button>
      </DeleteConfirm>
    </PermissionGate>
  );

  const addButton = (
    <Button icon={<Plus size={16} />} onClick={() => setIsAdding(true)}>
      Додати позицію
    </Button>
  );

  return (
    <PermissionGate resource="orders" action="read">
      <PageHeader
        title={`Замовлення ${order.orderNumber}`}
        description="Позиції, суми та статус"
        actions={
          <Space wrap>
            <StatusTag dictionary={ORDER_STATUS} value={order.status} />
            {/* Available in every status: a fulfilled order is the one most
                likely to be ordered again. */}
            {duplicateAction}
            {canWrite && hasTransitions ? (
              <Button
                type="primary"
                icon={<ArrowRightLeft size={16} />}
                onClick={() => setIsMoving(true)}
              >
                Змінити статус
              </Button>
            ) : null}
          </Space>
        }
      />

      {conflictAlert}

      <div className="mb-4">
        <Meta order={order} />
      </div>

      <PermissionGate
        resource="orders"
        action="write"
        fallback={
          <Card
            title="Дані замовлення"
            extra={
              <>
                {deleteAction}
                <BackButton href="/orders" />
              </>
            }
          >
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Контакт">{order.contactId ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="Угода">{order.dealId ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="Примітки">
                <ShowMoreText text={order.notes} limit={400} />
              </Descriptions.Item>
            </Descriptions>
          </Card>
        }
      >
        <Form<OrderFormValues> {...formProps}>
          <FormCard
            title="Дані замовлення"
            isSaving={isSaving}
            {...(canSubmit ? { onSubmit: submit } : {})}
            extra={deleteAction}
            backHref="/orders"
          >
            {fields}
          </FormCard>
        </Form>
      </PermissionGate>

      <Card className="mt-4" title="Позиції" extra={isEditable ? addButton : null}>
        <OrderItemsTable
          items={toViews(order)}
          currency={order.currency}
          isEditable={isEditable}
          isPending={isItemPending}
          {...(isEditable
            ? {
                onQuantityChange: (item: OrderItemView, quantity: number) =>
                  updateItem.mutate(
                    { itemId: item.id, version: order.version, quantity },
                    { onError: handleItemError },
                  ),
                onRemove: (item: OrderItemView) =>
                  removeItem.mutate(
                    { itemId: item.id, version: order.version },
                    { onError: handleItemError },
                  ),
                emptyAction: addButton,
              }
            : {})}
        />

        <div className="mt-4">
          <OrderTotals
            subtotal={order.subtotal}
            discountTotal={order.discountTotal}
            taxTotal={order.taxTotal}
            total={order.total}
            currency={order.currency}
          />
        </div>
      </Card>

      <AddItemModal
        open={isAdding}
        onClose={() => setIsAdding(false)}
        currency={order.currency}
        order={order}
        onConflict={handleConflict}
      />

      <StatusTransitionModal
        open={isMoving}
        onClose={() => setIsMoving(false)}
        order={order}
        onConflict={handleConflict}
      />
    </PermissionGate>
  );
}
