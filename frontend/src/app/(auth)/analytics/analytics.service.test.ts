import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import {
  AnalyticsService,
  isModuleUnavailable,
  toSalesSummaryParams,
  toStockHealthParams,
  toTopProductsParams,
} from './analytics.service';
import {
  MAX_LIMIT,
  MAX_RANGE_DAYS,
  describeRangeIssue,
  resolveLimit,
  resolveRange,
  resolveThreshold,
  toWireRange,
} from './analytics.validation';

const get = vi.fn();
const download = vi.fn();

// Only the transport is replaced: `ApiError` has to stay the real class, or the
// service and the test would each recognise a different one.
vi.mock('@/shared/api', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    http: {
      get: (...args: unknown[]) => get(...args),
      download: (...args: unknown[]) => download(...args),
    },
  };
});

const RANGE = { from: '2026-01-01T00:00:00.000Z', to: '2026-01-31T00:00:00.000Z' };

describe('toWireRange', () => {
  it('turns a calendar day into the instant that opens it', () => {
    expect(toWireRange({ from: '2026-01-01', to: '2026-01-31' }).from).toBe(
      '2026-01-01T00:00:00.000Z',
    );
  });

  it('ends the window at the next midnight, so the last day is included', () => {
    // The interval is half-open: ending at the day's own midnight would ask for
    // a window holding nothing that happened on it.
    expect(toWireRange({ from: '2026-01-01', to: '2026-01-31' }).to).toBe(
      '2026-02-01T00:00:00.000Z',
    );
  });

  it('passes an instant through unchanged', () => {
    expect(toWireRange(RANGE)).toEqual(RANGE);
  });
});

describe('resolveRange', () => {
  it('fills in a window when the query string names none', () => {
    const range = resolveRange(undefined, undefined);

    expect(describeRangeIssue(range)).toBeNull();
    expect(Date.parse(range.from)).toBeLessThan(Date.parse(range.to));
  });

  it('ignores an unreadable date rather than asking for it', () => {
    expect(resolveRange('not-a-date', '2026-01-31').to).toBe('2026-01-31');
    expect(resolveRange('not-a-date', '2026-01-31').from).not.toBe('not-a-date');
  });
});

describe('describeRangeIssue', () => {
  it('accepts an ordinary window', () => {
    expect(describeRangeIssue({ from: '2026-01-01', to: '2026-01-31' })).toBeNull();
  });

  it('refuses a window that runs backwards', () => {
    expect(describeRangeIssue({ from: '2026-02-01', to: '2026-01-01' })).toContain('раніша');
  });

  it('refuses a window wider than the API scans', () => {
    expect(describeRangeIssue({ from: '2024-01-01', to: '2026-01-01' })).toContain(
      String(MAX_RANGE_DAYS),
    );
  });
});

describe('resolveLimit and resolveThreshold', () => {
  it('falls back when the value is not a whole positive number', () => {
    expect(resolveLimit('abc')).toBe(10);
    expect(resolveLimit('0')).toBe(10);
    expect(resolveThreshold('abc')).toBe(5);
  });

  it('clamps rather than rejects, so a hand-edited link still opens', () => {
    expect(resolveLimit('5000')).toBe(MAX_LIMIT);
  });

  it('keeps a value the API accepts', () => {
    expect(resolveLimit('20')).toBe(20);
    expect(resolveThreshold('0')).toBe(0);
  });
});

describe('query parameters', () => {
  it('sends the period with the sales summary', () => {
    expect(toSalesSummaryParams({ ...RANGE, period: 'week' })).toEqual({
      ...RANGE,
      period: 'week',
      ownerId: undefined,
    });
  });

  it('sends the limit with the top products', () => {
    expect(toTopProductsParams({ ...RANGE, limit: 5 })).toMatchObject({ limit: 5 });
  });

  it('sends no period with the stock health, which looks at the present', () => {
    const params = toStockHealthParams({ threshold: 5, limit: 10 });

    expect(params).toEqual({ threshold: 5, limit: 10, warehouseId: undefined });
  });
});

describe('isModuleUnavailable', () => {
  it('recognises a route the API build does not serve', () => {
    expect(isModuleUnavailable(new ApiError({ status: 404, code: 'NOT_FOUND', message: '' }))).toBe(
      true,
    );
  });

  it('recognises a build the request never reached', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: '' })),
    ).toBe(true);
  });

  it('leaves a genuine failure to the error handler', () => {
    expect(isModuleUnavailable(new ApiError({ status: 500, code: 'INTERNAL', message: '' }))).toBe(
      false,
    );
    expect(isModuleUnavailable(new Error('boom'))).toBe(false);
  });
});

describe('AnalyticsService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads each report from its own route', async () => {
    await AnalyticsService.salesSummary({ ...RANGE, period: 'day' });
    await AnalyticsService.dealFunnel(RANGE);
    await AnalyticsService.topProducts({ ...RANGE, limit: 10 });
    await AnalyticsService.ownerPerformance({ ...RANGE, limit: 10 });
    await AnalyticsService.stockHealth({ threshold: 5, limit: 10 });

    expect(get.mock.calls.map(([path]) => path)).toEqual([
      '/analytics/sales-summary',
      '/analytics/deal-funnel',
      '/analytics/top-products',
      '/analytics/owner-performance',
      '/analytics/stock-health',
    ]);
  });

  it('passes the abort signal through, so a changed period cancels the old read', async () => {
    const controller = new AbortController();

    await AnalyticsService.dealFunnel(RANGE, controller.signal);

    expect(get).toHaveBeenCalledWith('/analytics/deal-funnel', {
      params: { ...RANGE, ownerId: undefined },
      signal: controller.signal,
    });
  });
});

describe('AnalyticsService export', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('exports each report from its own export route with the JSON format added', async () => {
    await AnalyticsService.exportSalesSummary({ ...RANGE, period: 'day' });
    await AnalyticsService.exportDealFunnel(RANGE);
    await AnalyticsService.exportTopProducts({ ...RANGE, limit: 10 });
    await AnalyticsService.exportOwnerPerformance({ ...RANGE, limit: 10 });
    await AnalyticsService.exportStockHealth({ threshold: 5, limit: 10 });

    expect(download.mock.calls.map(([path]) => path)).toEqual([
      '/analytics/sales-summary/export',
      '/analytics/deal-funnel/export',
      '/analytics/top-products/export',
      '/analytics/owner-performance/export',
      '/analytics/stock-health/export',
    ]);
  });

  // The most important guarantee of the whole feature: a report exported from
  // the screen must carry exactly the parameters the screen is showing — the
  // same conversion the JSON read uses, plus the format the export needs.
  it('sends the same query the on-screen report used, with format=csv added', async () => {
    await AnalyticsService.exportSalesSummary({ ...RANGE, period: 'week', ownerId: 'owner-1' });

    expect(download).toHaveBeenCalledWith('/analytics/sales-summary/export', {
      params: { ...RANGE, period: 'week', ownerId: 'owner-1', format: 'csv' },
    });
  });

  it('carries the limit and threshold into the stock health export unchanged', async () => {
    await AnalyticsService.exportStockHealth({ threshold: 7, limit: 20, warehouseId: 'wh-1' });

    expect(download).toHaveBeenCalledWith('/analytics/stock-health/export', {
      params: { threshold: 7, limit: 20, warehouseId: 'wh-1', format: 'csv' },
    });
  });

  it('passes the abort signal through to the export request', async () => {
    const controller = new AbortController();

    await AnalyticsService.exportTopProducts({ ...RANGE, limit: 5 }, controller.signal);

    expect(download).toHaveBeenCalledWith('/analytics/top-products/export', {
      params: { ...RANGE, limit: 5, format: 'csv' },
      signal: controller.signal,
    });
  });
});
