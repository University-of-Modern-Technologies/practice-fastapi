'use client';

import { Alert, Button } from 'antd';
import { Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { DataTable, ModuleUnavailable, PageHeader, PermissionGate } from '@/components';
import { useListParams, usePermissionScope, useReportError } from '@/shared/hooks';
import { hasActiveTicketFilters, useTicketTableColumns, useTicketTableFilters } from './_hooks';
import { useTickets } from './helpdesk.queries';
import { isModuleUnavailable, toTicketListQuery } from './helpdesk.service';
import { TICKET_FILTERS, type Ticket, type TicketFilter } from './helpdesk.types';

const LIST_DEFAULTS = { sortBy: 'openedAt', sortOrder: 'desc' } as const;

/**
 * Says out loud what the narrowed list already does silently. A viewer whose
 * grant is scoped to `OWN` gets a page that is complete from the server's point
 * of view and mysteriously short from theirs; without this line the missing
 * rows read as a broken list rather than as the access they were given.
 */
function OwnScopeNotice() {
  return (
    <Alert
      type="info"
      showIcon
      className="mb-4"
      message="Ви бачите лише свої звернення"
      description="Ваша роль має область «Тільки свої»: у списку — звернення, де відповідальний ви. Щоб бачити звернення колег, потрібна область «Усі записи»."
    />
  );
}

function TicketsList() {
  const router = useRouter();
  const scope = usePermissionScope('helpdesk', 'read');
  const reportError = useReportError();

  const { params, setParams, resetParams } = useListParams<TicketFilter>({
    filters: TICKET_FILTERS,
    defaults: LIST_DEFAULTS,
  });

  const { data, isLoading, isFetching, isError, error } = useTickets(toTicketListQuery(params));

  const unavailable = isModuleUnavailable(error);

  useEffect(() => {
    // A section this build does not serve is explained on the page itself, so
    // it must not also arrive as a failure notification.
    if (isError && !unavailable) reportError(error);
  }, [isError, unavailable, error, reportError]);

  const columns = useTicketTableColumns();
  const filters = useTicketTableFilters({
    params,
    onChange: setParams,
    onReset: resetParams,
    scope,
  });

  const createButton = (
    <PermissionGate resource="helpdesk" action="write" fallback={null}>
      <Button type="primary" icon={<Plus size={16} />} onClick={() => router.push('/helpdesk/new')}>
        Нове звернення
      </Button>
    </PermissionGate>
  );

  const header = (
    <PageHeader
      title="Звернення"
      description="Запити клієнтів з усіх каналів — від першого листа до закриття"
      actions={unavailable ? null : createButton}
    />
  );

  if (unavailable) {
    return (
      <>
        {header}
        <ModuleUnavailable missing="звернення служби підтримки" requirement="підтримка потрібна" />
      </>
    );
  }

  // An untouched list with nothing in it invites the first record; a filtered
  // one that came back empty is a different message entirely.
  const isFiltered = hasActiveTicketFilters(params);

  return (
    <>
      {header}

      {scope === 'OWN' ? <OwnScopeNotice /> : null}

      <DataTable<Ticket, TicketFilter>
        tableId="helpdesk"
        columns={columns}
        page={data}
        isLoading={isLoading || isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={(ticket) => router.push(`/helpdesk/${ticket.id}`)}
        filters={filters}
        emptyText={isFiltered ? 'За цим запитом звернень не знайдено' : 'Звернень ще немає'}
        {...(isFiltered ? {} : { emptyAction: createButton })}
      />
    </>
  );
}

export default function HelpdeskPage() {
  return (
    <PermissionGate resource="helpdesk" action="read">
      <TicketsList />
    </PermissionGate>
  );
}
