'use client';

import { Form, Input, Switch } from 'antd';
import { FormCard, PageHeader, PermissionGate, zodRule } from '@/components';
import { useWarehouseForm } from '../_hooks';
import { warehouseCodeSchema, warehouseNameSchema } from '../warehouse.validation';

export default function NewWarehousePage() {
  const { form, submit, isSaving } = useWarehouseForm();

  return (
    <PermissionGate resource="warehouse" action="write">
      <PageHeader title="Новий склад" description="Код задається один раз і надалі незмінний" />

      <FormCard title="Дані складу" onSubmit={submit} isSaving={isSaving} backHref="/warehouse">
        <Form form={form} layout="vertical" initialValues={{ isActive: true }}>
          <Form.Item name="code" label="Код" rules={[zodRule(warehouseCodeSchema)]}>
            <Input placeholder="MAIN" style={{ textTransform: 'uppercase' }} />
          </Form.Item>

          <Form.Item name="name" label="Назва" rules={[zodRule(warehouseNameSchema)]}>
            <Input placeholder="Головний склад" />
          </Form.Item>

          <Form.Item name="isActive" label="Активний" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </FormCard>
    </PermissionGate>
  );
}
