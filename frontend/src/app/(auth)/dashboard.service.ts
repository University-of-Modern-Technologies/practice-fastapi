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
 * Reads the three reports the overview is built from.
 *
 * Both ends of the window are sent. Only `from` used to be, on the grounds
 * that the API would close the window itself — but it closed it at the moment
 * of the call, so the overview slid forward a day at a time while the data
 * stayed where it was, and the cards emptied out on their own. A window named
 * at both ends is also a stable cache key, which was the other thing the old
 * arrangement was trying to buy.
 */
export const DashboardService = {
  salesSummary: (query: DashboardRangeQuery, signal?: AbortSignal): Promise<SalesSummaryReport> =>
    http.get<SalesSummaryReport>(ROUTES.salesSummary, {
      params: { from: query.from, to: query.to, period: 'day' },
      ...(signal ? { signal } : {}),
    }),

  dealFunnel: (query: DashboardRangeQuery, signal?: AbortSignal): Promise<DealFunnelReport> =>
    http.get<DealFunnelReport>(ROUTES.dealFunnel, {
      params: { from: query.from, to: query.to },
      ...(signal ? { signal } : {}),
    }),

  stockHealth: (query: StockHealthQuery, signal?: AbortSignal): Promise<StockHealthReport> =>
    http.get<StockHealthReport>(ROUTES.stockHealth, {
      params: { threshold: query.threshold, limit: query.limit },
      ...(signal ? { signal } : {}),
    }),
};
