import { http } from '@/shared/api';
import type {
  DashboardRangeQuery,
  DealFunnelReport,
  SalesSummaryReport,
  StockHealthQuery,
  StockHealthReport,
} from './dashboard.types';

const ROUTES = {
  salesSummary: '/analytics/sales-summary',
  dealFunnel: '/analytics/deal-funnel',
  stockHealth: '/analytics/stock-health',
} as const;

/**
 * Reads the three reports the overview is built from. Only `from` is sent: the
 * API closes the window at the moment of the call, so the client does not have
 * to put its own clock into the cache key and refetch on every render.
 */
export const DashboardService = {
  salesSummary: (query: DashboardRangeQuery, signal?: AbortSignal): Promise<SalesSummaryReport> =>
    http.get<SalesSummaryReport>(ROUTES.salesSummary, {
      params: { from: query.from, period: 'day' },
      ...(signal ? { signal } : {}),
    }),

  dealFunnel: (query: DashboardRangeQuery, signal?: AbortSignal): Promise<DealFunnelReport> =>
    http.get<DealFunnelReport>(ROUTES.dealFunnel, {
      params: { from: query.from },
      ...(signal ? { signal } : {}),
    }),

  stockHealth: (query: StockHealthQuery, signal?: AbortSignal): Promise<StockHealthReport> =>
    http.get<StockHealthReport>(ROUTES.stockHealth, {
      params: { threshold: query.threshold, limit: query.limit },
      ...(signal ? { signal } : {}),
    }),
};
