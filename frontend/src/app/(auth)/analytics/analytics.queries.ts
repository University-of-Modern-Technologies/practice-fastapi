'use client';

import {
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import type { DownloadedFile } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { AnalyticsService, isModuleUnavailable } from './analytics.service';
import type {
  DealFunnelQuery,
  DealFunnelReport,
  OwnerPerformanceQuery,
  OwnerPerformanceReport,
  SalesSummaryQuery,
  SalesSummaryReport,
  StockHealthQuery,
  StockHealthReport,
  TopProductsQuery,
  TopProductsReport,
} from './analytics.types';

/**
 * Every report is cached under its own key with its full query inside it.
 * Changing the period therefore reads a different entry instead of showing the
 * previous window's numbers under the new dates.
 */
export const analyticsKeys = {
  all: ['analytics'] as const,
  salesSummary: (query: SalesSummaryQuery) =>
    [...analyticsKeys.all, 'sales-summary', query] as const,
  dealFunnel: (query: DealFunnelQuery) => [...analyticsKeys.all, 'deal-funnel', query] as const,
  topProducts: (query: TopProductsQuery) => [...analyticsKeys.all, 'top-products', query] as const,
  ownerPerformance: (query: OwnerPerformanceQuery) =>
    [...analyticsKeys.all, 'owner-performance', query] as const,
  stockHealth: (query: StockHealthQuery) => [...analyticsKeys.all, 'stock-health', query] as const,
};

const MAX_ATTEMPTS = 2;

/** A missing section is an answer, not a hiccup: retrying it only delays the notice. */
const retry = (failureCount: number, error: Error): boolean =>
  !isModuleUnavailable(error) && failureCount < MAX_ATTEMPTS;

/** Reports are recomputed on the server; a minute-old answer is still current enough. */
const STALE_TIME_MS = 60_000;

interface ReportOptions {
  /** False while the chosen period is not usable — no request is worth sending. */
  readonly enabled?: boolean;
}

export const useSalesSummary = (
  query: SalesSummaryQuery,
  options: ReportOptions = {},
): UseQueryResult<SalesSummaryReport> =>
  useQuery({
    queryKey: analyticsKeys.salesSummary(query),
    queryFn: ({ signal }) => AnalyticsService.salesSummary(query, signal),
    enabled: options.enabled ?? true,
    staleTime: STALE_TIME_MS,
    retry,
  });

export const useDealFunnel = (
  query: DealFunnelQuery,
  options: ReportOptions = {},
): UseQueryResult<DealFunnelReport> =>
  useQuery({
    queryKey: analyticsKeys.dealFunnel(query),
    queryFn: ({ signal }) => AnalyticsService.dealFunnel(query, signal),
    enabled: options.enabled ?? true,
    staleTime: STALE_TIME_MS,
    retry,
  });

export const useTopProducts = (
  query: TopProductsQuery,
  options: ReportOptions = {},
): UseQueryResult<TopProductsReport> =>
  useQuery({
    queryKey: analyticsKeys.topProducts(query),
    queryFn: ({ signal }) => AnalyticsService.topProducts(query, signal),
    enabled: options.enabled ?? true,
    staleTime: STALE_TIME_MS,
    retry,
  });

export const useOwnerPerformance = (
  query: OwnerPerformanceQuery,
  options: ReportOptions = {},
): UseQueryResult<OwnerPerformanceReport> =>
  useQuery({
    queryKey: analyticsKeys.ownerPerformance(query),
    queryFn: ({ signal }) => AnalyticsService.ownerPerformance(query, signal),
    enabled: options.enabled ?? true,
    staleTime: STALE_TIME_MS,
    retry,
  });

export const useStockHealth = (
  query: StockHealthQuery,
  options: ReportOptions = {},
): UseQueryResult<StockHealthReport> =>
  useQuery({
    queryKey: analyticsKeys.stockHealth(query),
    queryFn: ({ signal }) => AnalyticsService.stockHealth(query, signal),
    enabled: options.enabled ?? true,
    staleTime: STALE_TIME_MS,
    retry,
  });

/**
 * Hands the browser a file the same way a saved link would: a throwaway
 * object URL, a click on an invisible anchor, then the URL is released. There
 * is no other API for "save this blob under this name" outside a form submit.
 */
const saveDownloadedFile = (file: DownloadedFile, fallbackName: string): void => {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename ?? fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

/**
 * One mutation shape for every report's CSV. The download itself is passed in
 * already bound to the query currently on screen, so triggering it later from
 * a click can never send a window the user is no longer looking at.
 */
export const useExportReport = (
  download: (signal?: AbortSignal) => Promise<DownloadedFile>,
  fallbackName: string,
): UseMutationResult<void, Error, void> => {
  const { reportFailure } = useMutationFeedback();

  return useMutation<void, Error, void>({
    mutationFn: async () => saveDownloadedFile(await download(), fallbackName),
    onError: reportFailure,
  });
};
