import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import { fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';
import AnalyticsPage from './page';
import type {
  DealFunnelReport,
  OwnerPerformanceReport,
  SalesSummaryReport,
  StockHealthReport,
  TopProductsReport,
} from './analytics.types';

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return {
    ...actual,
    http: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
      download: vi.fn(),
    },
  };
});

// The page keeps its filters in the query string via `useListParams`, which
// needs an App Router context this test does not mount. A page with no
// filters open (like Integrations) never hits this hook, but Analytics does.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => '/analytics',
  useSearchParams: () => new URLSearchParams(),
}));

const { http } = await import('@/shared/api');

const RANGE = { from: '2026-01-01T00:00:00.000Z', to: '2026-02-01T00:00:00.000Z' };

const SALES_SUMMARY: SalesSummaryReport = {
  ...RANGE,
  period: 'day',
  totals: { orderCount: 0, revenue: '0.00', averageOrderValue: '0.00' },
  series: [],
};
const DEAL_FUNNEL: DealFunnelReport = { ...RANGE, stages: [], conversions: [] };
const TOP_PRODUCTS: TopProductsReport = { ...RANGE, limit: 10, items: [] };
const OWNER_PERFORMANCE: OwnerPerformanceReport = { ...RANGE, items: [] };
const STOCK_HEALTH: StockHealthReport = { threshold: 5, limit: 10, items: [] };

/** Answers every JSON report route with a report that has something in it to read. */
const stubReports = (): void => {
  vi.mocked(http.get).mockImplementation((path: string) => {
    if (path === '/analytics/sales-summary') return Promise.resolve(SALES_SUMMARY);
    if (path === '/analytics/deal-funnel') return Promise.resolve(DEAL_FUNNEL);
    if (path === '/analytics/top-products') return Promise.resolve(TOP_PRODUCTS);
    if (path === '/analytics/owner-performance') return Promise.resolve(OWNER_PERFORMANCE);
    if (path === '/analytics/stock-health') return Promise.resolve(STOCK_HEALTH);
    return Promise.reject(new Error(`unexpected route ${path}`));
  });
};

const show = (): void => {
  renderWithProviders(<AnalyticsPage />, { permissions: ['analytics:read'] });
};

/**
 * jsdom does not implement the object-URL API a download needs, so the test
 * environment gets the same throwaway stand-in a browser would answer with.
 * The anchor's own `click` is stubbed too — jsdom would otherwise try to
 * navigate to the fake blob URL, which it cannot resolve.
 */
const stubFileSave = (): { readonly downloads: string[] } => {
  const downloads: string[] = [];
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn().mockReturnValue('blob:mock'),
    revokeObjectURL: vi.fn(),
  });

  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download);
  });

  return { downloads };
};

describe('Аналітика — вивантаження звіту', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('вивантажує звіт з тими самими параметрами, що показані на екрані', async () => {
    stubReports();
    vi.mocked(http.download).mockResolvedValue({ blob: new Blob(['x']), filename: 'report.csv' });
    stubFileSave();

    show();
    await screen.findByText('Продажі');

    const [csvButton] = screen.getAllByRole('button', { name: /CSV/ });
    fireEvent.click(csvButton as HTMLElement);

    await waitFor(() => {
      expect(http.download).toHaveBeenCalledWith(
        '/analytics/sales-summary/export',
        expect.anything(),
      );
    });

    const readCall = vi
      .mocked(http.get)
      .mock.calls.find(([path]) => path === '/analytics/sales-summary');
    const exportCall = vi
      .mocked(http.download)
      .mock.calls.find(([path]) => path === '/analytics/sales-summary/export');

    // The strongest guarantee the feature makes: the export asked for exactly
    // the window the report on screen was just read with, plus the format.
    expect(exportCall?.[1]).toMatchObject({
      params: { ...(readCall?.[1] as { params: object }).params, format: 'csv' },
    });
  });

  it('називає файл так, як сервер назвав його в заголовку відповіді', async () => {
    stubReports();
    vi.mocked(http.download).mockResolvedValue({
      blob: new Blob(['x']),
      filename: 'sales-summary-2026-01.csv',
    });
    const { downloads } = stubFileSave();

    show();
    await screen.findByText('Продажі');

    const [csvButton] = screen.getAllByRole('button', { name: /CSV/ });
    fireEvent.click(csvButton as HTMLElement);

    await waitFor(() => {
      expect(downloads).toContain('sales-summary-2026-01.csv');
    });
  });

  it('показує помилку сервера користувачу, а не мовчить', async () => {
    stubReports();
    vi.mocked(http.download).mockRejectedValue(
      new ApiError({ status: 500, code: 'INTERNAL', message: 'boom' }),
    );
    stubFileSave();

    show();
    await screen.findByText('Продажі');

    const [csvButton] = screen.getAllByRole('button', { name: /CSV/ });
    fireEvent.click(csvButton as HTMLElement);

    // The message is drawn by a toast after the rejected promise settles; under
    // a loaded full run that can take longer than findByText's default second.
    expect(
      await screen.findByText('Помилка на сервері', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it('не показує кнопку вивантаження і не падає, коли модуля аналітики немає', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 404, code: 'HTTP_404', message: '' }),
    );

    show();

    expect(await screen.findByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /CSV/ })).not.toBeInTheDocument();
    expect(http.download).not.toHaveBeenCalled();
  });
});
