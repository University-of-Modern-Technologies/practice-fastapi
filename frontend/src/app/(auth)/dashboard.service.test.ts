import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import { DashboardService } from './dashboard.service';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const stub = (body: unknown, status = 200) => {
  const fetchMock = vi.fn().mockResolvedValue(json(status, body));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const urlOf = (fetchMock: ReturnType<typeof vi.fn>): string => {
  const call = fetchMock.mock.calls[0] as [string, RequestInit];
  return call[0];
};

const salesSummary = {
  from: '2026-07-16T00:00:00.000Z',
  to: '2026-08-15T00:00:00.000Z',
  totals: { orderCount: 12, revenue: '4200.50', averageOrderValue: '350.04' },
};

describe('DashboardService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reads the sales summary from the window start, letting the API close the range', async () => {
    const fetchMock = stub({ data: salesSummary });

    await expect(DashboardService.salesSummary({ from: '2026-07-16' })).resolves.toEqual(
      salesSummary,
    );
    expect(urlOf(fetchMock)).toBe('/api/v1/analytics/sales-summary?from=2026-07-16&period=day');
  });

  it('reads the deal funnel for the same window without a period bucket', async () => {
    const fetchMock = stub({ data: { from: 'a', to: 'b', stages: [] } });

    await DashboardService.dealFunnel({ from: '2026-07-16' });

    expect(urlOf(fetchMock)).toBe('/api/v1/analytics/deal-funnel?from=2026-07-16');
  });

  it('asks stock health for a short list under the low-stock threshold', async () => {
    const fetchMock = stub({ data: { threshold: 5, limit: 5, items: [] } });

    await DashboardService.stockHealth({ threshold: 5, limit: 5 });

    expect(urlOf(fetchMock)).toBe('/api/v1/analytics/stock-health?threshold=5&limit=5');
  });

  it('keeps a zero threshold instead of dropping it as an empty filter', async () => {
    const fetchMock = stub({ data: { threshold: 0, limit: 5, items: [] } });

    await DashboardService.stockHealth({ threshold: 0, limit: 5 });

    expect(urlOf(fetchMock)).toBe('/api/v1/analytics/stock-health?threshold=0&limit=5');
  });

  it('surfaces a build without the analytics module as a 404 ApiError', async () => {
    stub({ error: { code: 'NOT_FOUND', message: 'Not Found' } }, 404);

    const error = await DashboardService.salesSummary({ from: '2026-07-16' }).catch(
      (cause: unknown) => cause,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404 });
  });

  it('surfaces an unreachable API as a NETWORK_ERROR rather than a crash', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const error = await DashboardService.dealFunnel({ from: '2026-07-16' }).catch(
      (cause: unknown) => cause,
    );

    expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' });
  });
});
