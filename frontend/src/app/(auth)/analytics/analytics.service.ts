import { ApiError, http, type DownloadedFile, type QueryValue } from '@/shared/api';
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

const ROUTES = {
  salesSummary: '/analytics/sales-summary',
  dealFunnel: '/analytics/deal-funnel',
  topProducts: '/analytics/top-products',
  ownerPerformance: '/analytics/owner-performance',
  stockHealth: '/analytics/stock-health',
} as const;

const EXPORT_ROUTES = {
  salesSummary: '/analytics/sales-summary/export',
  dealFunnel: '/analytics/deal-funnel/export',
  topProducts: '/analytics/top-products/export',
  ownerPerformance: '/analytics/owner-performance/export',
  stockHealth: '/analytics/stock-health/export',
} as const;

type Params = Readonly<Record<string, QueryValue>>;

/** Blank values are dropped by the HTTP client, so optionals pass through as-is. */
const toRangeParams = (query: { readonly from: string; readonly to: string }): Params => ({
  from: query.from,
  to: query.to,
});

export const toSalesSummaryParams = (query: SalesSummaryQuery): Params => ({
  ...toRangeParams(query),
  period: query.period,
  ownerId: query.ownerId,
});

export const toDealFunnelParams = (query: DealFunnelQuery): Params => ({
  ...toRangeParams(query),
  ownerId: query.ownerId,
});

export const toTopProductsParams = (query: TopProductsQuery): Params => ({
  ...toRangeParams(query),
  limit: query.limit,
});

export const toOwnerPerformanceParams = (query: OwnerPerformanceQuery): Params => ({
  ...toRangeParams(query),
  limit: query.limit,
});

export const toStockHealthParams = (query: StockHealthQuery): Params => ({
  threshold: query.threshold,
  limit: query.limit,
  warehouseId: query.warehouseId,
});

/**
 * Reporting is not part of every API build the client may be pointed at. A
 * route that is absent answers 404, and a build that does not serve it at all
 * fails at the transport — both mean "this section is not here", which is a
 * different thing from "the report failed" and must not be reported as one.
 */
export const isModuleUnavailable = (error: unknown): boolean => {
  if (!(error instanceof ApiError)) return false;
  return error.status === 404 || error.code === 'NETWORK_ERROR';
};

export const AnalyticsService = {
  salesSummary: (query: SalesSummaryQuery, signal?: AbortSignal): Promise<SalesSummaryReport> =>
    http.get<SalesSummaryReport>(ROUTES.salesSummary, {
      params: toSalesSummaryParams(query),
      ...(signal ? { signal } : {}),
    }),

  dealFunnel: (query: DealFunnelQuery, signal?: AbortSignal): Promise<DealFunnelReport> =>
    http.get<DealFunnelReport>(ROUTES.dealFunnel, {
      params: toDealFunnelParams(query),
      ...(signal ? { signal } : {}),
    }),

  topProducts: (query: TopProductsQuery, signal?: AbortSignal): Promise<TopProductsReport> =>
    http.get<TopProductsReport>(ROUTES.topProducts, {
      params: toTopProductsParams(query),
      ...(signal ? { signal } : {}),
    }),

  ownerPerformance: (
    query: OwnerPerformanceQuery,
    signal?: AbortSignal,
  ): Promise<OwnerPerformanceReport> =>
    http.get<OwnerPerformanceReport>(ROUTES.ownerPerformance, {
      params: toOwnerPerformanceParams(query),
      ...(signal ? { signal } : {}),
    }),

  stockHealth: (query: StockHealthQuery, signal?: AbortSignal): Promise<StockHealthReport> =>
    http.get<StockHealthReport>(ROUTES.stockHealth, {
      params: toStockHealthParams(query),
      ...(signal ? { signal } : {}),
    }),

  /**
   * One export per report, built on the same `toXxxParams` the JSON read uses:
   * the file that comes down is guaranteed to describe the same window, owner
   * and limit as the numbers already on screen, because it is the same query.
   */
  exportSalesSummary: (query: SalesSummaryQuery, signal?: AbortSignal): Promise<DownloadedFile> =>
    http.download(EXPORT_ROUTES.salesSummary, {
      params: { ...toSalesSummaryParams(query), format: 'csv' },
      ...(signal ? { signal } : {}),
    }),

  exportDealFunnel: (query: DealFunnelQuery, signal?: AbortSignal): Promise<DownloadedFile> =>
    http.download(EXPORT_ROUTES.dealFunnel, {
      params: { ...toDealFunnelParams(query), format: 'csv' },
      ...(signal ? { signal } : {}),
    }),

  exportTopProducts: (query: TopProductsQuery, signal?: AbortSignal): Promise<DownloadedFile> =>
    http.download(EXPORT_ROUTES.topProducts, {
      params: { ...toTopProductsParams(query), format: 'csv' },
      ...(signal ? { signal } : {}),
    }),

  exportOwnerPerformance: (
    query: OwnerPerformanceQuery,
    signal?: AbortSignal,
  ): Promise<DownloadedFile> =>
    http.download(EXPORT_ROUTES.ownerPerformance, {
      params: { ...toOwnerPerformanceParams(query), format: 'csv' },
      ...(signal ? { signal } : {}),
    }),

  exportStockHealth: (query: StockHealthQuery, signal?: AbortSignal): Promise<DownloadedFile> =>
    http.download(EXPORT_ROUTES.stockHealth, {
      params: { ...toStockHealthParams(query), format: 'csv' },
      ...(signal ? { signal } : {}),
    }),
};
