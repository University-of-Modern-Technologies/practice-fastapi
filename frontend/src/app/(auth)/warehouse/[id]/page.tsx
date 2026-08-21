'use client';

import { Button, Descriptions, Form, Input, Switch } from 'antd';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import {
  CopyableValue,
  DateValue,
  EmptyState,
  FormCard,
  FormPageSkeleton,
  PageHeader,
  PermissionGate,
  zodRule,
} from '@/components';
import { useHasPermission } from '@/shared/hooks';
import { StockOperationModal } from '../_components';
import { useWarehouseForm } from '../_hooks';
import { useWarehouse } from '../warehouse.queries';
import { warehouseNameSchema } from '../warehouse.validation';

function WarehouseCard() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [isOperationOpen, setOperationOpen] = useState(false);
  const canWrite = useHasPermission('warehouse', 'write');

  const { data: warehouse, isLoading, isError } = useWarehouse(id);
  const { form, submit, isSaving } = useWarehouseForm(warehouse);

  if (isLoading) return <FormPageSkeleton fields={4} />;
  if (isError || !warehouse) return <EmptyState description="Склад не знайдено" />;

  return (
    <>
      <PageHeader
        title={`${warehouse.code} — ${warehouse.name}`}
        description="Картка складу"
        actions={
          <PermissionGate resource="warehouse" action="write" fallback={null}>
            <Button onClick={() => setOperationOpen(true)}>Операція зі складом</Button>
          </PermissionGate>
        }
      />

      <FormCard
        title="Дані складу"
        isSaving={isSaving}
        backHref="/warehouse"
        extra={
          <Link href={`/warehouse/stock?warehouseId=${warehouse.id}`}>
            <Button>Залишки складу</Button>
          </Link>
        }
        {...(canWrite ? { onSubmit: submit } : {})}
      >
        <Form form={form} layout="vertical">
          {/* The API answers `WAREHOUSE_CODE_IMMUTABLE`, so the field is read-only. */}
          <Form.Item name="code" label="Код" extra="Код складу змінити не можна">
            <Input disabled />
          </Form.Item>

          <Form.Item name="name" label="Назва" rules={[zodRule(warehouseNameSchema)]}>
            <Input />
          </Form.Item>

          <Form.Item name="isActive" label="Активний" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>

        <Descriptions size="small" column={1} className="mt-4">
          <Descriptions.Item label="Ідентифікатор">
            <CopyableValue value={warehouse.id} />
          </Descriptions.Item>
          <Descriptions.Item label="Створено">
            <DateValue value={warehouse.createdAt} withTime />
          </Descriptions.Item>
          <Descriptions.Item label="Оновлено">
            <DateValue value={warehouse.updatedAt} withTime />
          </Descriptions.Item>
        </Descriptions>
      </FormCard>

      <StockOperationModal
        open={isOperationOpen}
        onClose={() => setOperationOpen(false)}
        defaultWarehouseId={warehouse.id}
      />
    </>
  );
}

export default function WarehouseCardPage() {
  // The card is a separate component so that a refused visitor never mounts it:
  // arriving by a direct link must show the notice, not a page firing requests
  // the API answers with 403.
  return (
    <PermissionGate resource="warehouse" action="read">
      <WarehouseCard />
    </PermissionGate>
  );
}
