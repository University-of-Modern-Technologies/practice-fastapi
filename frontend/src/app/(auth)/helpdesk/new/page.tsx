'use client';

import { Form } from 'antd';
import { useRouter } from 'next/navigation';
import { FormCard, PageHeader, PermissionGate } from '@/components';
import { useTicketForm } from '../_hooks';
import type { TicketFormValues } from '../helpdesk.validation';

export default function NewTicketPage() {
  const router = useRouter();
  const { formProps, fields, conflictAlert, submit, isSaving } = useTicketForm({
    onSaved: (ticket) => router.replace(`/helpdesk/${ticket.id}`),
  });

  return (
    <PermissionGate resource="helpdesk" action="write">
      <PageHeader
        title="Нове звернення"
        // Neither the number nor the state is offered here: the server issues
        // the one and starts the other, and it moves on only by a transition.
        description="Номер присвоює система; звернення створюється у стані «Нове»"
      />

      {conflictAlert}

      <FormCard
        title="Дані звернення"
        isSaving={isSaving}
        onSubmit={submit}
        submitLabel="Створити"
        backHref="/helpdesk"
      >
        <Form<TicketFormValues> {...formProps}>{fields}</Form>
      </FormCard>
    </PermissionGate>
  );
}
