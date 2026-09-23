import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as ApiModule from '@/shared/api';
import {
  fireEvent,
  grants,
  renderWithProviders,
  routeParams,
  screen,
  testUser,
  waitFor,
} from '@/test/render';
import TransactionPage from './transactions/[id]/page';
import type { BankTransactionDetail } from './finance.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/finance/transactions/33333333-3333-3333-3333-333333333333',
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

const TRANSACTION_ID = '33333333-3333-3333-3333-333333333333';

const base: BankTransactionDetail = {
  id: TRANSACTION_ID,
  statementId: '44444444-4444-4444-4444-444444444444',
  externalId: 'stub-txn-0007',
  bookedAt: '2026-01-17T10:00:00.000Z',
  amount: '1250.00',
  currency: 'USD',
  direction: 'CREDIT',
  counterpartyName: 'Acme LLC',
  counterpartyAccount: null,
  reference: 'Оплата за послуги, січень, SO-1001',
  matchStatus: 'SUGGESTED',
  matchedOrderId: null,
  matchedAt: null,
  matchedById: null,
  version: 2,
  createdAt: '2026-01-17T10:05:00.000Z',
  updatedAt: '2026-01-17T10:05:00.000Z',
};

/** Two orders of the same amount — the seventh and eighth rows of the fixture. */
const twoCandidates: BankTransactionDetail = {
  ...base,
  candidates: [
    {
      orderId: 'ord-1',
      orderNumber: 'SO-1001',
      total: '1250.00',
      currency: 'USD',
      status: 'CONFIRMED',
      contactId: 'contact-1',
      placedAt: '2026-01-10T09:00:00.000Z',
    },
    {
      orderId: 'ord-2',
      orderNumber: 'SO-1002',
      total: '1250.00',
      currency: 'USD',
      status: 'PAID',
      contactId: 'contact-2',
      placedAt: '2026-01-02T09:00:00.000Z',
    },
  ],
};

const showCard = (transaction: BankTransactionDetail, specs: readonly string[]): void => {
  vi.mocked(http.get).mockResolvedValue(transaction);
  renderWithProviders(<TransactionPage params={routeParams({ id: TRANSACTION_ID })} />, {
    user: testUser({ permissions: grants(specs) }),
  });
};

beforeEach(() => {
  vi.mocked(http.get).mockReset();
  vi.mocked(http.post).mockReset();
  vi.mocked(http.delete).mockReset();
});

describe('Платіж — стан «потрібен вибір»', () => {
  it('показує всіх кандидатів, а не найкращого з них', async () => {
    showCard(twoCandidates, ['finance:read', 'finance:write', 'orders:read']);

    expect(await screen.findByText('SO-1001')).toBeInTheDocument();
    expect(screen.getByText('SO-1002')).toBeInTheDocument();
  });

  /*
   * The load-bearing assertion of this module. With two identical amounts in
   * front of them and no stated reason, the operator picks whichever is on top
   * — and the interface has turned a decision about money into a coin toss.
   */
  it('каже про кожного кандидата, чим саме він кандидат', async () => {
    showCard(twoCandidates, ['finance:read', 'finance:write', 'orders:read']);

    await screen.findByText('SO-1001');
    expect(screen.getByText('У призначенні платежу є номер SO-1001')).toBeInTheDocument();
    expect(screen.getAllByText('Сума збігається точно')).toHaveLength(2);
  });

  it('пояснює, що автоматично звести не можна саме через кількох кандидатів', async () => {
    showCard(twoCandidates, ['finance:read', 'finance:write', 'orders:read']);

    expect(await screen.findByText(/Автоматично звести не можна — вибір за людиною/)).toBeInTheDocument();
  });

  it('надсилає вибір людини як зведення з версією, яку показувала картка', async () => {
    showCard(twoCandidates, ['finance:read', 'finance:write', 'orders:read']);
    vi.mocked(http.post).mockResolvedValue({ ...base, matchStatus: 'MATCHED' });

    await screen.findByText('SO-1001');
    fireEvent.click(screen.getAllByRole('button', { name: /Звести з цим/ })[0] as HTMLElement);

    await waitFor(() => {
      expect(http.post).toHaveBeenCalledWith(`/finance/transactions/${TRANSACTION_ID}/match`, {
        version: 2,
        orderId: 'ord-1',
      });
    });
  });

  it('дає сказати, що не підходить жоден, а не змушує вибрати з переліку', async () => {
    showCard(twoCandidates, ['finance:read', 'finance:write', 'orders:read']);

    expect(await screen.findByRole('button', { name: /Жоден не підходить/ })).toBeInTheDocument();
  });

  it('читачеві показує підстави, але не дає кнопок вибору', async () => {
    showCard(twoCandidates, ['finance:read', 'orders:read']);

    await screen.findByText('SO-1001');
    expect(screen.getByText('У призначенні платежу є номер SO-1001')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Звести з цим/ })).not.toBeInTheDocument();
  });

  // The contract names neither the field carrying the candidates nor its
  // shape. A build that answers without them must not leave the page silently
  // pretending the payment is simply untied.
  it('прямо каже, коли стан обіцяє кандидатів, а відповідь їх не принесла', async () => {
    showCard(base, ['finance:read', 'finance:write', 'orders:read']);

    expect(await screen.findByText('Кандидатів не отримано')).toBeInTheDocument();
  });
});

describe('Платіж — стан «не зведено»', () => {
  const untied: BankTransactionDetail = { ...base, matchStatus: 'UNMATCHED' };

  // Same sentence as on the list, said where the operator has stopped to look
  // at one row and is most likely to read it as a fault.
  it('називає незведений платіж робочим станом, а не помилкою', async () => {
    showCard(untied, ['finance:read', 'finance:write', 'orders:read']);

    expect(await screen.findByText(/Це робочий стан, а не помилка/)).toBeInTheDocument();
  });

  it('пропонує ручне зведення тому, хто має право на запис', async () => {
    showCard(untied, ['finance:read', 'finance:write', 'orders:read']);

    expect(await screen.findByRole('button', { name: /Звести вручну/ })).toBeInTheDocument();
  });

  it('читачеві каже, хто може звести, замість того щоб показувати мертву кнопку', async () => {
    showCard(untied, ['finance:read', 'orders:read']);

    await screen.findByText(/Це робочий стан, а не помилка/);
    expect(screen.queryByRole('button', { name: /Звести вручну/ })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Звести платіж може той, хто має право на зміни у фінансах/),
    ).toBeInTheDocument();
  });
});

describe('Платіж — стан «зведено»', () => {
  const matched: BankTransactionDetail = {
    ...base,
    matchStatus: 'MATCHED',
    matchedOrderId: 'ord-1',
    matchedAt: '2026-01-18T08:00:00.000Z',
  };

  it('знімає зведення тією самою версією, яку показувала картка', async () => {
    showCard(matched, ['finance:read', 'finance:write', 'orders:read']);
    vi.mocked(http.delete).mockResolvedValue({ ...base, matchStatus: 'UNMATCHED' });

    fireEvent.click(await screen.findByRole('button', { name: /Зняти зведення/ }));

    await waitFor(() => {
      expect(http.delete).toHaveBeenCalledWith(`/finance/transactions/${TRANSACTION_ID}/match`, {
        params: { version: 2 },
      });
    });
  });

  it('не пропонує знімати зведення тому, хто не має права на запис', async () => {
    showCard(matched, ['finance:read', 'orders:read']);

    await screen.findByText(/Платіж зведено із замовленням/);
    expect(screen.queryByRole('button', { name: /Зняти зведення/ })).not.toBeInTheDocument();
  });
});

describe('Платіж — дозволи на розділ', () => {
  it('відмовляє в картці тому, хто не має фінансів у переліку дозволів', async () => {
    showCard(base, ['calls:read']);

    expect(await screen.findByText('Недостатньо прав')).toBeInTheDocument();
  });
});
