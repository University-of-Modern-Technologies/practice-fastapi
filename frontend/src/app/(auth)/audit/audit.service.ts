import { http, type Page, type QueryValue } from '@/shared/api';
import type { AuditHistoryQuery, AuditListQuery, AuditRecord } from './audit.types';

const ROUTE = '/audit';

const DEFAULT_PAGE_SIZE = 25;

/**
 * Blank filters are dropped by the HTTP client, so passing them through keeps
 * the caller from assembling a different query object per combination.
 */
const toParams = (query: AuditListQuery): Readonly<Record<string, QueryValue>> => ({
  page: query.page ?? 1,
  pageSize: query.pageSize ?? DEFAULT_PAGE_SIZE,
  actorId: query.actorId,
  action: query.action,
  entityType: query.entityType,
  entityId: query.entityId,
  createdFrom: query.createdFrom,
  createdTo: query.createdTo,
});

export const AuditService = {
  list: (query: AuditListQuery = {}): Promise<Page<AuditRecord>> =>
    http.get<Page<AuditRecord>>(ROUTE, { params: toParams(query) }),

  /** Everything the log holds about one record, newest first. */
  history: (
    resource: string,
    resourceId: string,
    query: AuditHistoryQuery = {},
  ): Promise<Page<AuditRecord>> =>
    http.get<Page<AuditRecord>>(
      `${ROUTE}/${encodeURIComponent(resource)}/${encodeURIComponent(resourceId)}`,
      { params: toParams(query) },
    ),

  getById: (id: string): Promise<AuditRecord> =>
    http.get<AuditRecord>(`${ROUTE}/${encodeURIComponent(id)}`),
};
