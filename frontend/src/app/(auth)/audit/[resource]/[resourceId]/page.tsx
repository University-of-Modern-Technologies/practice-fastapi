'use client';

import { Button, Drawer } from 'antd';
import Link from 'next/link';
import { use, useEffect, useState } from 'react';
import { BackButton, DataTable, PageHeader, PermissionGate } from '@/components';
import { useListParams, useReportError } from '@/shared/hooks';
import { AuditRecordDetails } from '../../_components';
import {
  AUDIT_FILTERS,
  AUDIT_PAGE_SIZE,
  useAuditTableColumns,
  useAuditTableFilters,
  type AuditFilter,
} from '../../_hooks';
import { useAuditHistory } from '../../audit.queries';
import {
  auditEntityLabel,
  auditEntityRoute,
  type AuditHistoryQuery,
  type AuditRecord,
} from '../../audit.types';

interface AuditHistoryPageProps {
  readonly params: Promise<{ readonly resource: string; readonly resourceId: string }>;
}

function AuditHistory({ resource, resourceId }: { resource: string; resourceId: string }) {
  const { params, setParams, resetParams } = useListParams<AuditFilter>({
    filters: AUDIT_FILTERS,
    defaults: { pageSize: AUDIT_PAGE_SIZE },
  });

  const [selected, setSelected] = useState<AuditRecord | null>(null);

  const query: AuditHistoryQuery = {
    page: params.page,
    pageSize: params.pageSize,
    ...(params.action ? { action: params.action } : {}),
    ...(params.createdFrom ? { createdFrom: params.createdFrom } : {}),
    ...(params.createdTo ? { createdTo: params.createdTo } : {}),
  };

  const { data, isFetching, isError, error } = useAuditHistory(resource, resourceId, query);
  const reportError = useReportError();

  useEffect(() => {
    if (isError) reportError(error);
  }, [isError, error, reportError]);

  // The entity is fixed by the route, so repeating it in every row adds nothing.
  const columns = useAuditTableColumns({ withEntity: false });
  const filters = useAuditTableFilters({ params, setParams, resetParams, withEntity: false });

  const route = auditEntityRoute(resource, resourceId);

  return (
    <>
      <PageHeader
        title={`Історія: ${auditEntityLabel(resource)}`}
        description={resourceId}
        actions={
          <>
            {route ? (
              <Link href={route}>
                <Button type="primary">Відкрити запис</Button>
              </Link>
            ) : null}
            <BackButton href="/audit" />
          </>
        }
      />

      <DataTable<AuditRecord, AuditFilter>
        tableId="audit-history"
        columns={columns}
        page={data}
        isLoading={isFetching}
        params={params}
        onParamsChange={setParams}
        onRowClick={setSelected}
        filters={filters}
        emptyText="Для цього запису подій ще немає"
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

export default function AuditHistoryPage({ params: routeParams }: AuditHistoryPageProps) {
  const { resource, resourceId } = use(routeParams);

  // The history is a separate component so that a refused visitor never mounts
  // it: arriving by a direct link must show the notice, not a page firing
  // requests the API answers with 403.
  return (
    <PermissionGate resource="audit" action="read">
      <AuditHistory resource={resource} resourceId={resourceId} />
    </PermissionGate>
  );
}
