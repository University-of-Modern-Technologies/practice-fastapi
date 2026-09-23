import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import type { Page, PermissionScope } from '@/shared/api';
import { grants, renderWithProviders, screen, testUser, waitFor } from '@/test/render';
import HelpdeskPage from './page';
import type { Ticket } from './helpdesk.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/helpdesk',
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

const ticket: Ticket = {
  id: '11111111-1111-1111-1111-111111111111',
  number: 'TKT-00000042',
  subject: 'Не приходить рахунок',
  body: 'Клієнт не отримав рахунок за серпень.',
  channel: 'EMAIL',
  status: 'OPEN',
  priority: 'HIGH',
  contactId: null,
  assigneeId: null,
  ownerId: '00000000-0000-0000-0000-000000000001',
  openedAt: '2026-08-12T15:23:45.123Z',
  resolvedAt: null,
  version: 3,
  createdAt: '2026-08-12T15:23:45.123Z',
  updatedAt: '2026-08-13T09:00:00.000Z',
};

const pageOf = (items: readonly Ticket[]): Page<Ticket> => ({
  items,
  page: 1,
  pageSize: 20,
  total: items.length,
});

/** The list as a role with the given scope on `helpdesk:read` would see it. */
const showList = (specs: readonly string[], scope: PermissionScope = 'ALL'): void => {
  renderWithProviders(<HelpdeskPage />, {
    user: testUser({ permissions: grants(specs, scope) }),
  });
};

beforeEach(() => {
  vi.mocked(http.get).mockReset();
  vi.mocked(http.get).mockResolvedValue(pageOf([ticket]));
});

describe('Список звернень — область доступу видно в інтерфейсі', () => {
  // The narrowed list is complete from the server's point of view and
  // mysteriously short from the viewer's; unexplained, it reads as a bug.
  it('каже читачеві з областю «тільки свої», що список звужено', async () => {
    showList(['helpdesk:read'], 'OWN');

    expect(await screen.findByText('Ви бачите лише свої звернення')).toBeInTheDocument();
  });

  it('нічого такого не каже тому, хто бачить усі звернення', async () => {
    showList(['helpdesk:read', 'helpdesk:write'], 'ALL');

    await screen.findByText(/TKT-00000042/);
    expect(screen.queryByText('Ви бачите лише свої звернення')).not.toBeInTheDocument();
  });

  // With scope OWN the control would either repeat what is already in force or
  // promise a widening the server will not grant.
  it('не пропонує фільтр «лише мої» тому, хто й так бачить лише свої', async () => {
    showList(['helpdesk:read'], 'OWN');

    await screen.findByText(/TKT-00000042/);
    expect(screen.queryByText('Лише мої')).not.toBeInTheDocument();
  });

  it('пропонує цей фільтр тому, хто бачить усіх', async () => {
    showList(['helpdesk:read'], 'ALL');

    expect(await screen.findByText('Лише мої')).toBeInTheDocument();
  });
});

describe('Список звернень — дозволи', () => {
  it('не показує кнопку створення без права на запис', async () => {
    showList(['helpdesk:read']);

    await screen.findByText(/TKT-00000042/);
    expect(screen.queryByRole('button', { name: /Нове звернення/ })).not.toBeInTheDocument();
  });

  it('показує кнопку створення тому, хто має право на запис', async () => {
    showList(['helpdesk:read', 'helpdesk:write']);

    expect(await screen.findByRole('button', { name: /Нове звернення/ })).toBeInTheDocument();
  });

  it('відмовляє в розділі тому, хто не має права читати', () => {
    showList(['contacts:read']);

    expect(screen.getByText('Недостатньо прав')).toBeInTheDocument();
  });
});

describe('Список звернень — збірка API без цього розділу', () => {
  it('пояснює відсутній розділ, а не показує помилку', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 404, code: 'NOT_FOUND', message: 'Not Found' }),
    );

    showList(['helpdesk:read', 'helpdesk:write']);

    expect(await screen.findByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    // Nothing to create in a section the server does not serve.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Нове звернення/ })).not.toBeInTheDocument();
    });
  });
});
