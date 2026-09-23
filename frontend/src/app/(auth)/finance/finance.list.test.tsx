import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import type { Page } from '@/shared/api';
import { grants, renderWithProviders, screen, testUser, waitFor } from '@/test/render';
import TransactionsPage from './transactions/page';
import type { BankTransaction } from './finance.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/finance/transactions',
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

/** The state most payments are in, and the one this section is written around. */
const unmatched: BankTransaction = {
  id: '33333333-3333-3333-3333-333333333333',
  statementId: '44444444-4444-4444-4444-444444444444',
  externalId: 'stub-txn-0009',
  bookedAt: '2026-01-21T10:00:00.000Z',
  amount: '4200.00',
  currency: 'USD',
  direction: 'DEBIT',
  counterpartyName: 'Міськсервіс',
  counterpartyAccount: null,
  reference: 'Оренда приміщення за січень',
  matchStatus: 'UNMATCHED',
  matchedOrderId: null,
  matchedAt: null,
  matchedById: null,
  version: 1,
  createdAt: '2026-01-21T10:05:00.000Z',
  updatedAt: '2026-01-21T10:05:00.000Z',
};

const pageOf = (items: readonly BankTransaction[]): Page<BankTransaction> => ({
  items,
  page: 1,
  pageSize: 20,
  total: items.length,
});

const showList = (specs: readonly string[]): void => {
  renderWithProviders(<TransactionsPage />, {
    user: testUser({ permissions: grants(specs) }),
  });
};

beforeEach(() => {
  vi.mocked(http.get).mockReset();
  vi.mocked(http.post).mockReset();
  vi.mocked(http.get).mockResolvedValue(pageOf([unmatched]));
});

describe('Платежі — розбіжність є робочим станом', () => {
  // The section's whole argument. A table where most rows say "not matched"
  // reads as a list of failures unless the page says what it is looking at.
  it('пояснює, що незведений платіж — це норма, а не поломка', async () => {
    showList(['finance:read']);

    expect(
      await screen.findByText('Розбіжність між випискою й замовленнями — робочий стан'),
    ).toBeInTheDocument();
  });

  it('називає стан «не зведено» словами, а не порожньою клітинкою', async () => {
    showList(['finance:read']);

    expect(await screen.findByText('Не зведено')).toBeInTheDocument();
    expect(screen.getByText('Оренда приміщення за січень')).toBeInTheDocument();
  });

  // The reference is what the matcher reads. Hiding it behind a click would
  // leave the operator unable to see why nothing matched.
  it('показує призначення платежу просто в переліку', async () => {
    showList(['finance:read']);

    await screen.findByText('Не зведено');
    expect(screen.getByPlaceholderText('Призначення або контрагент')).toBeInTheDocument();
  });

  // Every state is offered, including the two that need nothing done to them:
  // a filter listing only problems would turn the ledger into a defect queue.
  it('дає фільтрувати за всіма чотирма станами зведення', async () => {
    showList(['finance:read']);

    await screen.findByText('Не зведено');
    expect(screen.getByText('Стан зведення')).toBeInTheDocument();
  });
});

describe('Платежі — дозволи', () => {
  it('не показує автозведення без права на запис', async () => {
    showList(['finance:read']);

    await screen.findByText('Не зведено');
    expect(screen.queryByRole('button', { name: /Звести автоматично/ })).not.toBeInTheDocument();
  });

  it('показує автозведення тому, хто має право на запис', async () => {
    showList(['finance:read', 'finance:write']);

    expect(await screen.findByRole('button', { name: /Звести автоматично/ })).toBeInTheDocument();
  });

  /*
   * The case this module exists to create. Every other section hides rows
   * behind a scope; here a role holds no finance grant at all, and the answer
   * has to be a refusal rather than an empty table — somebody shown a blank
   * statement list would conclude that no money had ever come in.
   */
  it('відмовляє в розділі тому, хто не має фінансів у переліку дозволів', () => {
    renderWithProviders(<TransactionsPage />, {
      user: testUser({
        roles: ['viewer'],
        permissions: grants(['contacts:read', 'helpdesk:read', 'calls:read'], 'OWN'),
      }),
    });

    expect(screen.getByText('Недостатньо прав')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('не показує відмову як порожній перелік', () => {
    renderWithProviders(<TransactionsPage />, {
      user: testUser({ roles: ['viewer'], permissions: grants(['calls:read'], 'OWN') }),
    });

    expect(screen.queryByText('Платежів ще немає — імпортуйте виписку')).not.toBeInTheDocument();
    expect(screen.queryByText(/Розбіжність між випискою/)).not.toBeInTheDocument();
  });
});

describe('Платежі — збірка API без цього розділу', () => {
  it('пояснює відсутній розділ, а не показує помилку', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 404, code: 'NOT_FOUND', message: 'Not Found' }),
    );

    showList(['finance:read', 'finance:write']);

    expect(await screen.findByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Звести автоматично/ })).not.toBeInTheDocument();
    });
  });

  // Both answer 404. A build that serves finance but has lost one payment must
  // not be reported as a build without the section.
  it('не оголошує розділ відсутнім через один зниклий платіж', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 404, code: 'TRANSACTION_NOT_FOUND', message: 'Not Found' }),
    );

    showList(['finance:read']);

    await waitFor(() => {
      expect(
        screen.queryByText('Розділ недоступний у поточній збірці API'),
      ).not.toBeInTheDocument();
    });
  });
});
