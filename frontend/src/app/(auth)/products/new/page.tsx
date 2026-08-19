'use client';

import { Form } from 'antd';
import { useRouter } from 'next/navigation';
import { FormCard, PageHeader, PermissionGate } from '@/components';
import { useProductForm } from '../_hooks';
import type { ProductFormValues } from '../products.validation';

export default function NewProductPage() {
  const router = useRouter();
  const { formProps, fields, conflictAlert, submit, isSaving } = useProductForm({
    onSaved: (product) => router.replace(`/products/${product.id}`),
  });

  return (
    <PermissionGate resource="products" action="write">
      <PageHeader title="Новий товар" description="Позиція каталогу для замовлень" />

      {conflictAlert}

      <FormCard
        title="Дані товару"
        isSaving={isSaving}
        onSubmit={submit}
        submitLabel="Створити"
        backHref="/products"
      >
        <Form<ProductFormValues> {...formProps}>{fields}</Form>
      </FormCard>
    </PermissionGate>
  );
}
