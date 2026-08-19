'use client';

import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/shared/api';
import { DateTime } from '@/lib/date-time';
import { DashboardService } from './dashboard.service';
import type {
  DashboardRangeQuery,
  DealFunnelReport,
  SalesSummaryReport,
  StockHealthQuery,
  StockHealthReport,
} from './dashboard.types';

/** Reporting window of the overview, in days. */
export const DASHBOARD_RANGE_DAYS = 30;
export const LOW_STOCK_THRESHOLD = 5;
export const LOW_STOCK_LIMIT = 5;

export const dashboardKeys = {
  all: ['dashboard'] as const,
  salesSummary: (query: DashboardRangeQuery) =>
    [...dashboardKeys.all, 'sales-summary', query] as const,
  dealFunnel: (query: DashboardRangeQuery) => [...dashboardKeys.all, 'deal-funnel', query] as const,
  stockHealth: (query: StockHealthQuery) => [...dashboardKeys.all, 'stock-health', query] as const,
};

/**
 * The analytics module exists in one API build and not in the other. A missing
 * route is therefore not a failure to report but a fact about the deployment:
 * the block leaves the page and the rest of the overview keeps working.
 */
export const isAnalyticsUnavailable = (error: unknown): boolean =>
  error instanceof ApiError && (error.status === 404 || error.code === 'NETWORK_ERROR');

/** What a block needs to decide between a skeleton, its content, and nothing. */
export interface AnalyticsBlock<T> {
  readonly data: T | undefined;
  readonly isLoading: boolean;
  /** The module is absent from this API build — render nothing at all. */
  readonly isUnavailable: boolean;
}

// Retrying a route that does not exist only delays the moment the block gives
// up, and the answer would not change.
const ANALYTICS_OPTIONS = { retry: false, staleTime: 60_000 } as const;

const rangeQuery = (): DashboardRangeQuery => ({ from: DateTime.daysAgo(DASHBOARD_RANGE_DAYS) });

export const useSalesSummary = (enabled: boolean): AnalyticsBlock<SalesSummaryReport> => {
  const query = rangeQuery();
  const result = useQuery<SalesSummaryReport>({
    queryKey: dashboardKeys.salesSummary(query),
    queryFn: ({ signal }) => DashboardService.salesSummary(query, signal),
    enabled,
    ...ANALYTICS_OPTIONS,
  });

  return {
    data: result.data,
    isLoading: result.isLoading,
    isUnavailable: isAnalyticsUnavailable(result.error),
  };
};

export const useDealFunnel = (enabled: boolean): AnalyticsBlock<DealFunnelReport> => {
  const query = rangeQuery();
  const result = useQuery<DealFunnelReport>({
    queryKey: dashboardKeys.dealFunnel(query),
    queryFn: ({ signal }) => DashboardService.dealFunnel(query, signal),
    enabled,
    ...ANALYTICS_OPTIONS,
  });

  return {
    data: result.data,
    isLoading: result.isLoading,
    isUnavailable: isAnalyticsUnavailable(result.error),
  };
};

export const useStockHealth = (enabled: boolean): AnalyticsBlock<StockHealthReport> => {
  const query: StockHealthQuery = { threshold: LOW_STOCK_THRESHOLD, limit: LOW_STOCK_LIMIT };
  const result = useQuery<StockHealthReport>({
    queryKey: dashboardKeys.stockHealth(query),
    queryFn: ({ signal }) => DashboardService.stockHealth(query, signal),
    enabled,
    ...ANALYTICS_OPTIONS,
  });

  return {
    data: result.data,
    isLoading: result.isLoading,
    isUnavailable: isAnalyticsUnavailable(result.error),
  };
};
