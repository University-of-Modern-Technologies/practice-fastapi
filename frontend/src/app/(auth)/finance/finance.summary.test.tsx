import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import { grants, renderWithProviders, screen, testUser, waitFor } from '@/test/render';
import FinancePage from './page';
import type { BankStatement, FinanceSummary } from './finance.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/finance',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return {
    ...actual,
    http: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  };
});

const { http } = await import('@/shared/api');

const statement: BankStatement = {
  id: '44444444-4444-4444-4444-444444444444',
  externalId: 'stub-stmt-2026-01',
  accountLabel: 'Operating account',
  periodStart: '2026-01-01',
  periodEnd: '2026-01-31',
  openingBalance: '10000.00',
  closingBalance: '12750.00',
  currency: 'USD',
  importedAt: '2026-02-01T08:00:00.000Z',
  importedById: '00000000-0000-0000-0000-000000000001',
  createdAt: '2026-02-01T08:00:00.000Z',
  updatedAt: '2026-02-01T08:00:00.000Z',
};

const summary: FinanceSummary = {
  from: '2026-01-01T00:00:00.000Z',
  to: '2026-02-01T00:00:00.000Z',
  transactionCount: 12,
  inflow: '9000.00',
  outflow: '6250.00',
  net: '2750.00',
  statuses: [
    { status: 'MATCHED', count: 4, amount: '5000.00', share: 0.3333 },
    { status: 'SUGGESTED', count: 2, amount: '2500.00', share: 0.1667 },
    { status: 'UNMATCHED', count: 6, amount: '6750.00', share: 0.5 },
    { status: 'IGNORED', count: 0, amount: '0.00', share: 0 },
  ],
};

/** The overview reads two endpoints; the path decides which answer it gets. */
const answer = (path: string): unknown =>
  path.startsWith('/finance/summary')
    ? summary
    : { items: [statement], page: 1, pageSize: 20, total: 1 };

const showOverview = (specs: readonly string[]): void => {
  renderWithProviders(<FinancePage />, { user: testUser({ permissions: grants(specs) }) });
};

beforeEach(() => {
  vi.mocked(http.get).mockReset();
  vi.mocked(http.post).mockReset();
  vi.mocked(http.get).mockImplementation((path: string) => Promise.resolve(answer(path)) as never);
});

describe('Фінанси — підсумок за період', () => {
  // Money crosses the wire as a string and is rendered through the shared
  // formatter; the section must not grow a formatter of its own.
  it('показує надходження й списання як гроші, а не як числа', async () => {
    vi.mocked(http.get).mockImplementation((path: string) =>
      path === '/finance/summary'
        ? (Promise.resolve(summary) as never)
        : (new Promise(() => undefined) as never),
    );

    showOverview(['finance:read']);

    expect(await screen.findByText('Надходження')).toBeInTheDocument();
    expect(screen.getByText('Списання')).toBeInTheDocument();
    expect(screen.getByText(/9\s?000,00/)).toBeInTheDocument();
    expect(http.get).toHaveBeenCalledWith(
      '/finance/summary',
      expect.objectContaining({
        params: {
          from: '2026-01-01T00:00:00.000Z',
          to: '2026-02-01T00:00:00.000Z',
        },
      }),
    );
  });

  it('показує кількість транзакцій за період', async () => {
    showOverview(['finance:read']);

    await screen.findByText('Транзакцій');
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('показує імпортовані виписки з їхніми залишками', async () => {
    showOverview(['finance:read']);

    expect(await screen.findByText('Operating account')).toBeInTheDocument();
    expect(screen.getByText(/12\s?750,00/)).toBeInTheDocument();
  });
});

describe('Фінанси — дозволи', () => {
  it('не показує імпорту й автозведення без права на запис', async () => {
    showOverview(['finance:read']);

    await screen.findByText('Operating account');
    expect(screen.queryByRole('button', { name: /Імпортувати виписку/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Звести автоматично/ })).not.toBeInTheDocument();
  });

  it('показує обидві дії тому, хто має право на запис', async () => {
    showOverview(['finance:read', 'finance:write']);

    expect(await screen.findByRole('button', { name: /Імпортувати виписку/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Звести автоматично/ })).toBeInTheDocument();
  });

  /*
   * The new case this change introduces. Other sections narrow what a role sees;
   * this one is absent from a role's permissions altogether, and the answer has
   * to read as "no access" rather than as an empty section — a person shown a
   * blank finance page would conclude the company had received no money.
   */
  it('відмовляє в розділі ролі, у якої фінансів немає взагалі', () => {
    renderWithProviders(<FinancePage />, {
      user: testUser({
        roles: ['viewer'],
        permissions: grants(['contacts:read', 'helpdesk:read', 'calls:read'], 'OWN'),
      }),
    });

    expect(screen.getByText('Недостатньо прав')).toBeInTheDocument();
    expect(screen.queryByText('Підсумок за період')).not.toBeInTheDocument();
    expect(screen.queryByText('Виписки')).not.toBeInTheDocument();
  });
});

describe('Фінанси — недоступний банк', () => {
  it('пояснює відсутній розділ, а не показує помилку', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 404, code: 'NOT_FOUND', message: 'Not Found' }),
    );

    showOverview(['finance:read', 'finance:write']);

    expect(await screen.findByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Імпортувати виписку/ })).not.toBeInTheDocument();
    });
  });
});
