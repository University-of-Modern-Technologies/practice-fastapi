import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DealStage } from '@/shared/constants';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import { fireEvent, renderWithProviders, routeParams, screen, waitFor } from '@/test/render';
import DealPage from './[id]/page';
import type { Deal } from './deals.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/deals/1',
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

const DEAL_ID = '11111111-1111-1111-1111-111111111111';

const deal = (stage: DealStage): Deal => ({
  id: DEAL_ID,
  ownerId: '00000000-0000-0000-0000-000000000001',
  contactId: null,
  title: 'Постачання серверів',
  stage,
  amount: '12000.00',
  currency: 'USD',
  probability: 40,
  version: 3,
  expectedCloseDate: '2026-09-01',
  closedAt: null,
  createdAt: '2026-08-01T10:00:00.000Z',
  updatedAt: '2026-08-10T10:00:00.000Z',
});

const conflict = (code: string, details?: unknown): ApiError =>
  new ApiError({ status: 409, code, message: 'Конфлікт', details });

const showCard = (stage: DealStage, permissions: readonly string[]): void => {
  vi.mocked(http.get).mockResolvedValue(deal(stage));
  renderWithProviders(<DealPage params={routeParams({ id: DEAL_ID })} />, { permissions });
};

const openCard = async (stage: DealStage): Promise<void> => {
  showCard(stage, ['deals:read', 'deals:write']);
  await screen.findByText('Постачання серверів');
};

/** Picks a stage and confirms the dialog — the only path a transition takes. */
const moveTo = async (label: string): Promise<void> => {
  fireEvent.click(screen.getByRole('button', { name: label }));
  const confirm = await screen.findByRole('button', { name: 'Перевести' });
  fireEvent.click(confirm);
};

beforeEach(() => {
  vi.mocked(http.post).mockReset();
});

describe('Картка угоди — стадії', () => {
  it('пропонує лише ті переходи, які дозволяє машина станів', async () => {
    await openCard('LEAD');

    expect(screen.getByRole('button', { name: 'Кваліфіковано' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Пропозиція' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Виграно' })).not.toBeInTheDocument();
  });

  it('дає обидві розвилки з пропозиції', async () => {
    await openCard('PROPOSAL');

    expect(screen.getByRole('button', { name: 'Виграно' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Втрачено' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Кваліфіковано' })).not.toBeInTheDocument();
  });

  it('не пропонує жодного переходу з кінцевої стадії', async () => {
    await openCard('WON');

    expect(screen.getByText('Угоду закрито')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Втрачено' })).not.toBeInTheDocument();
  });
});

describe('Картка угоди — два значення 409', () => {
  it('пропонує перечитати запис, коли стадію змінив хтось інший', async () => {
    await openCard('PROPOSAL');
    vi.mocked(http.post).mockRejectedValue(conflict('DEAL_CONCURRENT_MODIFICATION'));

    await moveTo('Виграно');

    expect(await screen.findByText('Запис змінив інший користувач')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Перечитати' })).toBeInTheDocument();
    expect(screen.queryByText('Такий перехід неможливий')).not.toBeInTheDocument();
  });

  // Re-reading changes nothing here: the domain refused the move itself, so the
  // page names the moves that were open instead of offering a reload.
  it('пояснює відмову домену без пропозиції перечитати', async () => {
    await openCard('PROPOSAL');
    vi.mocked(http.post).mockRejectedValue(
      conflict('INVALID_DEAL_STAGE_TRANSITION', { from: 'WON', to: 'LOST', allowed: [] }),
    );

    await moveTo('Втрачено');

    expect(await screen.findByText('Такий перехід неможливий')).toBeInTheDocument();
    expect(screen.queryByText('Запис змінив інший користувач')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Перечитати' })).not.toBeInTheDocument();
  });

  it('називає стадії, до яких перехід був можливий', async () => {
    await openCard('PROPOSAL');
    vi.mocked(http.post).mockRejectedValue(
      conflict('INVALID_DEAL_STAGE_TRANSITION', {
        from: 'QUALIFIED',
        to: 'WON',
        allowed: ['PROPOSAL'],
      }),
    );

    await moveTo('Виграно');

    expect(await screen.findByText(/дозволено перейти до: Пропозиція/)).toBeInTheDocument();
  });
});

describe('Картка угоди — дозволи', () => {
  it('читачеві не пропонує змінювати стадію', async () => {
    showCard('PROPOSAL', ['deals:read']);
    await screen.findByText('Постачання серверів');

    await waitFor(() => {
      expect(screen.getByText('Немає прав на зміну стадії')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Виграно' })).not.toBeInTheDocument();
  });
});
