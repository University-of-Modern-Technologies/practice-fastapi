import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import { fireEvent, renderWithProviders, routeParams, screen, waitFor } from '@/test/render';
import TicketPage from './[id]/page';
import type { Ticket } from './helpdesk.types';
import type { TicketStatus } from '@/shared/constants';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/helpdesk/1',
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

const TICKET_ID = '11111111-1111-1111-1111-111111111111';

const ticket = (status: TicketStatus): Ticket => ({
  id: TICKET_ID,
  number: 'TKT-00000042',
  subject: 'Не приходить рахунок',
  body: 'Клієнт не отримав рахунок за серпень.',
  channel: 'EMAIL',
  status,
  priority: 'HIGH',
  contactId: null,
  assigneeId: null,
  ownerId: '00000000-0000-0000-0000-000000000001',
  openedAt: '2026-08-12T15:23:45.123Z',
  resolvedAt: null,
  version: 3,
  createdAt: '2026-08-12T15:23:45.123Z',
  updatedAt: '2026-08-13T09:00:00.000Z',
});

const apiError = (status: number, code: string, details?: unknown): ApiError =>
  new ApiError({ status, code, message: 'Відмова', details });

const showCard = (status: TicketStatus, permissions: readonly string[]): void => {
  vi.mocked(http.get).mockResolvedValue(ticket(status));
  renderWithProviders(<TicketPage params={routeParams({ id: TICKET_ID })} />, { permissions });
};

const openCard = async (status: TicketStatus): Promise<void> => {
  showCard(status, ['helpdesk:read', 'helpdesk:write']);
  await screen.findByRole('heading', { name: /TKT-00000042/ });
};

/** Picks a state and confirms the dialog — the only path a transition takes. */
const moveTo = async (label: string): Promise<void> => {
  fireEvent.click(screen.getByRole('button', { name: label }));
  const confirm = await screen.findByRole('button', { name: 'Перевести' });
  fireEvent.click(confirm);
};

beforeEach(() => {
  vi.mocked(http.post).mockReset();
  vi.mocked(http.get).mockReset();
});

describe('Картка звернення — переходи стану', () => {
  it('пропонує лише ті переходи, які дозволяє машина станів', async () => {
    await openCard('NEW');

    expect(screen.getByRole('button', { name: 'У роботі' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Закрито' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Розвʼязано' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Очікує відповіді' })).not.toBeInTheDocument();
  });

  it('дає з роботи всі три виходи', async () => {
    await openCard('OPEN');

    expect(screen.getByRole('button', { name: 'Очікує відповіді' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Розвʼязано' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Закрито' })).toBeInTheDocument();
  });

  // Reopening is a published move, and it is the one the operator reaches for
  // when a customer comes back on a ticket that was already answered.
  it('дозволяє повернути розвʼязане звернення в роботу', async () => {
    await openCard('RESOLVED');

    expect(screen.getByRole('button', { name: 'У роботі' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Закрито' })).toBeInTheDocument();
  });

  it('не пропонує жодного переходу із закритого звернення', async () => {
    await openCard('CLOSED');

    expect(screen.getByText('Звернення закрито')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'У роботі' })).not.toBeInTheDocument();
  });

  it('надсилає перехід із версією, яку прочитала картка', async () => {
    await openCard('OPEN');
    vi.mocked(http.post).mockResolvedValue(ticket('RESOLVED'));

    await moveTo('Розвʼязано');

    await waitFor(() => {
      expect(http.post).toHaveBeenCalledWith(
        `/helpdesk/tickets/${TICKET_ID}/transitions`,
        expect.objectContaining({ version: 3, toStatus: 'RESOLVED' }),
      );
    });
  });
});

describe('Картка звернення — дві різні відмови', () => {
  it('пропонує перечитати запис, коли звернення змінив хтось інший', async () => {
    await openCard('OPEN');
    vi.mocked(http.post).mockRejectedValue(apiError(409, 'TICKET_CONCURRENT_MODIFICATION'));

    await moveTo('Розвʼязано');

    expect(await screen.findByText('Запис змінив інший користувач')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Перечитати' })).toBeInTheDocument();
    expect(screen.queryByText('Такий перехід неможливий')).not.toBeInTheDocument();
  });

  // Re-reading changes nothing here: the machine refused the move itself, so
  // the page names the moves that were open instead of offering a reload.
  it('пояснює відмову машини станів без пропозиції перечитати', async () => {
    await openCard('OPEN');
    vi.mocked(http.post).mockRejectedValue(
      apiError(422, 'TICKET_TRANSITION_NOT_ALLOWED', { from: 'CLOSED', to: 'OPEN', allowed: [] }),
    );

    await moveTo('Розвʼязано');

    expect(await screen.findByText('Такий перехід неможливий')).toBeInTheDocument();
    expect(screen.queryByText('Запис змінив інший користувач')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Перечитати' })).not.toBeInTheDocument();
  });

  it('називає стани, до яких перехід був можливий', async () => {
    await openCard('OPEN');
    vi.mocked(http.post).mockRejectedValue(
      apiError(422, 'TICKET_TRANSITION_NOT_ALLOWED', {
        from: 'PENDING',
        to: 'RESOLVED',
        allowed: ['OPEN', 'CLOSED'],
      }),
    );

    await moveTo('Розвʼязано');

    expect(await screen.findByText(/дозволено перейти до: У роботі, Закрито/)).toBeInTheDocument();
  });

  // The contract names the code and the status of this refusal but not the
  // body that comes with it, so a build that sends none must still leave the
  // page with something to say.
  it('не падає, коли відмова прийшла без подробиць', async () => {
    await openCard('OPEN');
    vi.mocked(http.post).mockRejectedValue(apiError(422, 'TICKET_TRANSITION_NOT_ALLOWED'));

    await moveTo('Розвʼязано');

    expect(await screen.findByText('Такий перехід неможливий')).toBeInTheDocument();
  });
});

describe('Картка звернення — дозволи', () => {
  it('читачеві не пропонує змінювати стан', async () => {
    showCard('OPEN', ['helpdesk:read']);
    await screen.findByRole('heading', { name: /TKT-00000042/ });

    await waitFor(() => {
      expect(screen.getByText('Немає прав на зміну стану')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Розвʼязано' })).not.toBeInTheDocument();
  });

  it('читачеві показує звернення, але не форму редагування', async () => {
    showCard('OPEN', ['helpdesk:read']);
    await screen.findByRole('heading', { name: /TKT-00000042/ });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Зберегти' })).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Видалити' })).not.toBeInTheDocument();
  });
});

describe('Картка звернення — чужий запис', () => {
  // A record someone else owns answers 404 rather than 403, so the page must
  // not claim the ticket was deleted.
  it('не стверджує, що запис видалено, коли він може бути просто чужим', async () => {
    vi.mocked(http.get).mockRejectedValue(apiError(404, 'TICKET_NOT_FOUND'));
    renderWithProviders(<TicketPage params={routeParams({ id: TICKET_ID })} />, {
      permissions: ['helpdesk:read'],
    });

    expect(await screen.findByText('Звернення не знайдено')).toBeInTheDocument();
    expect(screen.getByText(/недоступний вашій області доступу/)).toBeInTheDocument();
  });
});
