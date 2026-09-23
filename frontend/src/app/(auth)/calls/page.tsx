'use client';

import { Alert } from 'antd';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { DataTable, ModuleUnavailable, PageHeader, PermissionGate } from '@/components';
import { useListParams, usePermissionScope, useReportError } from '@/shared/hooks';
import { SyncCallsButton } from './_components';
import { hasActiveCallFilters, useCallTableColumns, useCallTableFilters } from './_hooks';
import { useCalls } from './calls.queries';
import { isModuleUnavailable, toCallListQuery } from './calls.service';
import { CALL_FILTERS, type Call, type CallFilter } from './calls.types';

const LIST_DEFAULTS = { sortBy: 'startedAt', sortOrder: 'desc' } as const;

/**
 * Says out loud what the narrowed list already does silently. A viewer whose
 * grant is scoped to `OWN` gets a page that is complete from the server's point
 * of view and mysteriously short from theirs; without this line the missing
 * rows read as a broken list rather than as the access they were given.
 *
 * The second sentence is the part specific to this journal, and it is the one
 * nobody could infer: the scope is strictly "the calls that are mine", and a
 * call nobody has taken is nobody's — so it is not in this list at all. "Mine"
 * and "everyone's" therefore do not add up to the journal the way they do in a
 * section where every record has an owner from the moment it exists.
 */
function OwnScopeNotice() {
  return (
    <Alert
      type="info"
      showIcon
      className="mb-4"
      message="Ви бачите лише свої дзвінки"
      description="Ваша роль має область «Тільки свої»: у журналі — дзвінки, де відповідальний ви. Дзвінки, яких ще ніхто не взяв, сюди не потрапляють — щоб бачити весь журнал, потрібна область «Усі записи»."
    />
  );
}

/**
 * The consequence of that scope at the one moment it looks like a malfunction.
 *
 * A pull under a narrowed scope brings in calls that are nobody's yet, so the
 * server reports records created while the list on screen does not move. Left
 * unexplained, the operator presses the button again — and gets the same
 * nothing, because the second pull skips what the first one created.
 */
function InvisibleSyncNotice({
  created,
  onClose,
}: {
  readonly created: number;
  readonly onClose: () => void;
}) {
  return (
    <Alert
      type="info"
      showIcon
      closable
      className="mb-4"
      message={`Синхронізація додала дзвінків: ${created}. У вашому списку їх немає`}
      description="Нові дзвінки приходять без відповідального, а ваша область доступу показує лише ті, де відповідальний ви. Дзвінки в журналі є — щоб їх побачити, потрібна область «Усі записи»."
      onClose={onClose}
    />
  );
}

/**
 * The provider is reachable only through the sync action. Its being down says
 * nothing about the records already pulled, so the journal stays on screen and
 * this line names what actually failed.
 */
function ProviderDownNotice({ onClose }: { readonly onClose: () => void }) {
  return (
    <Alert
      type="warning"
      showIcon
      closable
      className="mb-4"
      message="Провайдер телефонії недоступний"
      description="Нові дзвінки зараз не підтягуються. Журнал нижче читається як звичайно — спробуйте синхронізацію пізніше."
      onClose={onClose}
    />
  );
}

function CallsList() {
  const router = useRouter();
  const scope = usePermissionScope('calls', 'read');
  const reportError = useReportError();

  const [isProviderDown, setIsProviderDown] = useState(false);
  /** Calls the last pull created that this viewer's scope keeps out of the list. */
  const [invisibleCreated, setInvisibleCreated] = useState(0);

  const { params, setParams, resetParams } = useListParams<CallFilter>({
    filters: CALL_FILTERS,
    defaults: LIST_DEFAULTS,
  });

  const { data, isLoading, isFetching, isError, error } = useCalls(toCallListQuery(params));

  const unavailable = isModuleUnavailable(error);

  useEffect(() => {
    // A section this build does not serve is explained on the page itself, so
    // it must not also arrive as a failure notification.
    if (isError && !unavailable) reportError(error);
  }, [isError, unavailable, error, reportError]);

  const columns = useCallTableColumns();
  const filters = useCallTableFilters({
    params,
    onChange: setParams,
    onReset: resetParams,
    scope,
  });

  const syncButton = (
    <PermissionGate resource="calls" action="write" fallback={null}>
      <SyncCallsButton
        onProviderUnavailable={() => setIsProviderDown(true)}
        onSynced={(result) => {
          setIsProviderDown(false);
          // A narrowed scope cannot see a call nobody has taken, so a pull that
          // created records leaves this list exactly as it was.
          setInvisibleCreated(scope === 'OWN' ? result.created : 0);
        }}
      />
    </PermissionGate>
  );

  const header = (
    <PageHeader
      title="Дзвінки"
      description="Журнал розмов: що відбулося на лінії і до чого це стосується"
      actions={unavailable ? null : syncButton}
    />
  );

  if (unavailable) {
    return (
      <>
        {header}
        <ModuleUnavailable missing="журнал дзвінків" requirement="телефонія потрібна" />
      </>
    );
  }

  // An untouched journal with nothing in it is waiting for its first pull; a
  // filtered one that came back empty is a different message entirely.
  const isFiltered = hasActiveCallFilters(params);

  return (
    <>
      {header}

      {scope === 'OWN' ? <OwnScopeNotice /> : null}

      {isProviderDown ? <ProviderDownNotice onClose={() => setIsProviderDown(false)} /> : null}

      {invisibleCreated > 0 ? (
        <InvisibleSyncNotice created={invisibleCreated} onClose={() => setInvisibleCreated(0)} />
      ) : null}

      <DataTable<Call, CallFilter>
        tableId="calls"
        columns={columns}
        page={data}
        isLoading={isLoading || isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={(call) => router.push(`/calls/${call.id}`)}
        filters={filters}
        emptyText={
          isFiltered
            ? 'За цим запитом дзвінків не знайдено'
            : 'Журнал порожній — дзвінки зʼявляться після синхронізації'
        }
        // Nothing is created by hand here: a call enters the journal only from
        // the provider, so the empty state offers the pull rather than a form.
        {...(isFiltered ? {} : { emptyAction: syncButton })}
      />
    </>
  );
}

export default function CallsPage() {
  return (
    <PermissionGate resource="calls" action="read">
      <CallsList />
    </PermissionGate>
  );
}
