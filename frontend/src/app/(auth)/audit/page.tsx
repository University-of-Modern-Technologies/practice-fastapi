'use client';

import { Drawer } from 'antd';
import { useEffect, useState } from 'react';
import { DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams, useReportError } from '@/shared/hooks';
import { AuditRecordDetails } from './_components';
import {
  AUDIT_FILTERS,
  AUDIT_PAGE_SIZE,
  useAuditTableColumns,
  useAuditTableFilters,
  type AuditFilter,
} from './_hooks';
import { useAuditList } from './audit.queries';
import type { AuditListQuery, AuditRecord } from './audit.types';

function AuditLog() {
  const { params, setParams, resetParams } = useListParams<AuditFilter>({
    filters: AUDIT_FILTERS,
    defaults: { pageSize: AUDIT_PAGE_SIZE },
  });

  const [selected, setSelected] = useState<AuditRecord | null>(null);

  // Spread conditionally: an optional query field must be absent, not undefined.
  const query: AuditListQuery = {
    page: params.page,
    pageSize: params.pageSize,
    ...(params.action ? { action: params.action } : {}),
    ...(params.entityType ? { entityType: params.entityType } : {}),
    ...(params.entityId ? { entityId: params.entityId } : {}),
    ...(params.actorId ? { actorId: params.actorId } : {}),
    ...(params.createdFrom ? { createdFrom: params.createdFrom } : {}),
    ...(params.createdTo ? { createdTo: params.createdTo } : {}),
  };

  const { data, isFetching, isError, error } = useAuditList(query);
  const reportError = useReportError();

  useEffect(() => {
    if (isError) reportError(error);
  }, [isError, error, reportError]);

  const columns = useAuditTableColumns();
  const filters = useAuditTableFilters({ params, setParams, resetParams });

  return (
    <>
      <PageHeader
        title="Аудит"
        description="Журнал змін, які застосунок записав. Лише для читання."
      />

      <DataTable<AuditRecord, AuditFilter>
        tableId="audit"
        columns={columns}
        page={data}
        isLoading={isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={setSelected}
        filters={filters}
        emptyText="Подій за цими умовами немає"
      />

      <Drawer
        width={720}
        title="Подія аудиту"
        open={selected !== null}
        onClose={() => setSelected(null)}
        destroyOnHidden
      >
        {selected ? <AuditRecordDetails record={selected} /> : null}
      </Drawer>
    </>
  );
}

export default function AuditPage() {
  // The list is a separate component so that a refused visitor never mounts it:
  // arriving by a direct link must show the notice, not a page firing requests
  // the API answers with 403.
  return (
    <PermissionGate resource="audit" action="read">
      <AuditLog />
    </PermissionGate>
  );
}
