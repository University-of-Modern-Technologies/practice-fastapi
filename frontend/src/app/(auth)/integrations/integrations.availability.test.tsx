import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import { fireEvent, renderWithProviders, screen } from '@/test/render';
import IntegrationsPage from './page';
import type { DeliveryHealth } from './integrations.types';

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return {
    ...actual,
    http: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  };
});

const { http } = await import('@/shared/api');

const HEALTH: DeliveryHealth = {
  transport: 'stub',
  circuitState: 'closed',
  consecutiveFailures: 0,
  lastErrorAt: null,
  openedAt: null,
};

const MISSING_SECTION = 'Розділ недоступний у поточній збірці API';

const notFound = (code: string): ApiError =>
  new ApiError({ status: 404, code, message: 'Not found' });

const show = (): void => {
  renderWithProviders(<IntegrationsPage />, { permissions: ['integrations:read'] });
};

const search = (id: string): void => {
  fireEvent.change(screen.getByPlaceholderText('Номер відправлення'), { target: { value: id } });
  fireEvent.click(screen.getByRole('button', { name: 'Знайти' }));
};

describe('Інтеграції — деградація без модуля', () => {
  it('пояснює відсутність розділу замість помилки, коли маршруту немає', async () => {
    vi.mocked(http.get).mockRejectedValue(notFound('HTTP_404'));

    show();

    expect(await screen.findByText(MISSING_SECTION)).toBeInTheDocument();
    expect(screen.queryByText('Пошук відправлення')).not.toBeInTheDocument();
  });

  it('вважає розділ відсутнім і тоді, коли запит не дійшов до API', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 0, code: 'NETWORK_ERROR', message: 'fetch failed' }),
    );

    show();

    expect(await screen.findByText(MISSING_SECTION)).toBeInTheDocument();
  });

  // Both answers are a 404; only the code tells them apart. Treating them alike
  // would let a mistyped number wipe out the section the operator is working in.
  it('не гасить розділ, коли відправлення з таким номером просто немає', async () => {
    vi.mocked(http.get).mockImplementation((path: string) =>
      path.startsWith('/integrations/delivery/shipments/')
        ? Promise.reject(notFound('DELIVERY_REJECTED'))
        : Promise.resolve(HEALTH),
    );

    show();
    await screen.findByText('Пошук відправлення');

    search('SHP-НЕМАЄ');

    expect(await screen.findByText('Відправлення не знайдено')).toBeInTheDocument();
    expect(screen.getByText('Пошук відправлення')).toBeInTheDocument();
    expect(screen.queryByText(MISSING_SECTION)).not.toBeInTheDocument();
  });

  it('гасить розділ, коли 404 приходить від самого пошуку без коду інтеграції', async () => {
    vi.mocked(http.get).mockImplementation((path: string) =>
      path.startsWith('/integrations/delivery/shipments/')
        ? Promise.reject(notFound('HTTP_404'))
        : Promise.resolve(HEALTH),
    );

    show();
    await screen.findByText('Пошук відправлення');

    search('SHP-1');

    expect(await screen.findByText(MISSING_SECTION)).toBeInTheDocument();
  });
});
