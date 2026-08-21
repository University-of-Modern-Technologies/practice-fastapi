'use client';

import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query';
import type { Page } from '@/shared/api';
import { AuditService } from './audit.service';
import type { AuditHistoryQuery, AuditListQuery, AuditRecord } from './audit.types';

export const auditKeys = {
  all: ['audit'] as const,
  lists: () => [...auditKeys.all, 'list'] as const,
  list: (query: AuditListQuery) => [...auditKeys.lists(), query] as const,
  histories: () => [...auditKeys.all, 'history'] as const,
  /** The log of one record is its own cache entry, not a filtered main list. */
  history: (resource: string, resourceId: string, query: AuditHistoryQuery = {}) =>
    [...auditKeys.histories(), resource, resourceId, query] as const,
  detail: (id: string) => [...auditKeys.all, 'detail', id] as const,
};

export const useAuditList = (query: AuditListQuery): UseQueryResult<Page<AuditRecord>> =>
  useQuery({
    queryKey: auditKeys.list(query),
    queryFn: () => AuditService.list(query),
    // The log is append-only: the previous page may stay on screen while the
    // next one loads without ever showing a stale row as current.
    placeholderData: keepPreviousData,
  });

export const useAuditHistory = (
  resource: string,
  resourceId: string,
  query: AuditHistoryQuery = {},
): UseQueryResult<Page<AuditRecord>> =>
  useQuery({
    queryKey: auditKeys.history(resource, resourceId, query),
    queryFn: () => AuditService.history(resource, resourceId, query),
    enabled: resource !== '' && resourceId !== '',
    placeholderData: keepPreviousData,
  });

export const useAuditRecord = (id: string): UseQueryResult<AuditRecord> =>
  useQuery({
    queryKey: auditKeys.detail(id),
    queryFn: () => AuditService.getById(id),
    enabled: id !== '',
  });
