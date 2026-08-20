'use client';

import { Form } from 'antd';
import { useRouter } from 'next/navigation';
import { FormCard, PageHeader, PermissionGate } from '@/components';
import { useDealForm } from '../_hooks';
import type { DealFormValues } from '../deals.validation';

export default function NewDealPage() {
  const router = useRouter();
  const { formProps, fields, conflictAlert, submit, isSaving } = useDealForm({
    onSaved: (deal) => router.replace(`/deals/${deal.id}`),
  });

  return (
    <PermissionGate resource="deals" action="write">
      <PageHeader
        title="Нова угода"
        // The stage is not offered here: every deal starts as a lead and moves
        // on only through a transition.
        description="Угода створюється на стадії «Лід»"
      />

      {conflictAlert}

      <FormCard
        title="Дані угоди"
        isSaving={isSaving}
        onSubmit={submit}
        submitLabel="Створити"
        backHref="/deals"
      >
        <Form<DealFormValues> {...formProps}>{fields}</Form>
      </FormCard>
    </PermissionGate>
  );
}
