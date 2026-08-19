'use client';

import { Button, Card, Descriptions, Form, Tag } from 'antd';
import { Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { use } from 'react';
import {
  BackButton,
  CopyableValue,
  DateValue,
  DeleteConfirm,
  EmptyState,
  FormCard,
  FormPageSkeleton,
  MoneyValue,
  PageHeader,
  PermissionGate,
  ShowMoreText,
} from '@/components';
import { useMutationFeedback } from '@/shared/hooks';
import { useProductForm } from '../_hooks';
import { useDeleteProduct, useProduct } from '../products.queries';
import type { Product } from '../products.types';
import type { ProductFormValues } from '../products.validation';

const Meta = ({ product }: { readonly product: Product }) => (
  <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} bordered>
    <Descriptions.Item label="Ідентифікатор">
      <CopyableValue value={product.id} />
    </Descriptions.Item>
    <Descriptions.Item label="Поточна ціна">
      <MoneyValue value={product.unitPrice} currency={product.currency} showCurrency />
    </Descriptions.Item>
    <Descriptions.Item label="Створено">
      <DateValue value={product.createdAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Оновлено">
      <DateValue value={product.updatedAt} withTime />
    </Descriptions.Item>
  </Descriptions>
);

export default function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { reportSuccess } = useMutationFeedback();

  const { data: product, isLoading, isError, isFetching, refetch } = useProduct(id);
  const remove = useDeleteProduct(id);

  const { formProps, fields, conflictAlert, submit, isSaving, handleError } = useProductForm({
    product,
    // The card stays put after a save: the fresh version arrives through the
    // cache, so there is nowhere to navigate.
    onSaved: () => undefined,
    onReload: refetch,
    isReloading: isFetching,
  });

  if (isLoading) return <FormPageSkeleton />;
  if (isError || product === undefined) return <EmptyState description="Товар не знайдено" />;

  const onDelete = () => {
    // The same version the form holds: a delete can lose the race just as a save can.
    remove.mutate(product.version, {
      onSuccess: () => {
        reportSuccess('Товар видалено');
        router.replace('/products');
      },
      onError: handleError,
    });
  };

  const deleteAction = (
    <PermissionGate resource="products" action="delete" fallback={null}>
      <DeleteConfirm
        onConfirm={onDelete}
        isPending={remove.isPending}
        title="Видалити товар?"
        description="Позицію буде приховано з каталогу."
      >
        <Button danger icon={<Trash2 size={16} />} loading={remove.isPending}>
          Видалити
        </Button>
      </DeleteConfirm>
    </PermissionGate>
  );

  return (
    <PermissionGate resource="products" action="read">
      <PageHeader
        title={product.name}
        description={`Артикул ${product.sku}`}
        actions={
          <Tag color={product.isActive ? 'success' : 'default'}>
            {product.isActive ? 'Активний' : 'Вимкнено'}
          </Tag>
        }
      />

      {conflictAlert}

      <div className="mb-4">
        <Meta product={product} />
      </div>

      <PermissionGate
        resource="products"
        action="write"
        fallback={
          <Card
            title="Дані товару"
            extra={
              <>
                {deleteAction}
                <BackButton href="/products" />
              </>
            }
          >
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Категорія">{product.category ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="Опис">
                <ShowMoreText text={product.description} limit={400} />
              </Descriptions.Item>
            </Descriptions>
          </Card>
        }
      >
        <Form<ProductFormValues> {...formProps}>
          <FormCard
            title="Дані товару"
            isSaving={isSaving}
            onSubmit={submit}
            extra={deleteAction}
            backHref="/products"
          >
            {fields}
          </FormCard>
        </Form>
      </PermissionGate>
    </PermissionGate>
  );
}
