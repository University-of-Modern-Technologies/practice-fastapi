import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import type { Page, PermissionScope } from '@/shared/api';
import { fireEvent, grants, renderWithProviders, screen, testUser, waitFor } from '@/test/render';
import CallsPage from './page';
import type { Call } from './calls.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/calls',
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

/** The state a call arrives in: nobody has said yet what it was about. */
const untriaged: Call = {
  id: '22222222-2222-2222-2222-222222222222',
  externalId: 'pbx-000917',
  direction: 'INBOUND',
  disposition: 'ANSWERED',
  fromNumber: '+380671234567',
  toNumber: '+380442223344',
  startedAt: '2026-08-12T15:23:45.123Z',
  durationSeconds: 155,
  contactId: null,
  dealId: null,
  ownerId: null,
  recordingUrl: null,
  notes: null,
  version: 1,
  createdAt: '2026-08-12T15:24:00.000Z',
  updatedAt: '2026-08-12T15:24:00.000Z',
};

const pageOf = (items: readonly Call[]): Page<Call> => ({
  items,
  page: 1,
  pageSize: 20,
  total: items.length,
});

/** The journal as a role with the given scope on `calls:read` would see it. */
const showList = (specs: readonly string[], scope: PermissionScope = 'ALL'): void => {
  renderWithProviders(<CallsPage />, { user: testUser({ permissions: grants(specs, scope) }) });
};

beforeEach(() => {
  vi.mocked(http.get).mockReset();
  vi.mocked(http.post).mockReset();
  vi.mocked(http.get).mockResolvedValue(pageOf([untriaged]));
});

describe('Журнал дзвінків — непривʼязаний дзвінок є робочим станом', () => {
  // A call reaches the journal before anyone has decided what it was about.
  // Drawn as a missing value, that reads as data the system lost.
  it('показує дзвінок без контакту, угоди й власника як стан роботи, а не як поломку', async () => {
    showList(['calls:read']);

    expect(await screen.findByText('Ще не привʼязано')).toBeInTheDocument();
    expect(screen.getByText(/380671234567/)).toBeInTheDocument();
  });

  // The term goes to the numbers and the notes. A field labelled as a client
  // search would promise a lookup the API does not perform — and most calls
  // have no client to look up by.
  it('не обіцяє пошуку за клієнтом, якого журнал не виконує', async () => {
    showList(['calls:read']);

    await screen.findByText('Ще не привʼязано');
    expect(screen.getByPlaceholderText('Номер або нотатки')).toBeInTheDocument();
  });
});

describe('Журнал дзвінків — область доступу видно в інтерфейсі', () => {
  // The narrowed list is complete from the server's point of view and
  // mysteriously short from the viewer's; unexplained, it reads as a bug.
  it('каже читачеві з областю «тільки свої», що журнал звужено', async () => {
    showList(['calls:read'], 'OWN');

    expect(await screen.findByText('Ви бачите лише свої дзвінки')).toBeInTheDocument();
  });

  // The scope is strictly "the calls that are mine", and a call nobody has
  // taken is nobody's. The person reading a short list has no other way to
  // learn that a whole class of records is missing from it.
  it('каже прямо, що нічийні дзвінки у звужену вибірку не потрапляють', async () => {
    showList(['calls:read'], 'OWN');

    expect(
      await screen.findByText(/яких ще ніхто не взяв, сюди не потрапляють/),
    ).toBeInTheDocument();
  });

  it('нічого такого не каже тому, хто бачить усі дзвінки', async () => {
    showList(['calls:read'], 'ALL');

    await screen.findByText(/380671234567/);
    expect(screen.queryByText('Ви бачите лише свої дзвінки')).not.toBeInTheDocument();
  });

  it('не пропонує фільтр «лише мої» тому, хто й так бачить лише свої', async () => {
    showList(['calls:read'], 'OWN');

    await screen.findByText(/380671234567/);
    expect(screen.queryByText('Лише мої')).not.toBeInTheDocument();
  });
});

describe('Журнал дзвінків — дозволи', () => {
  it('не показує синхронізації без права на запис', async () => {
    showList(['calls:read']);

    await screen.findByText(/380671234567/);
    expect(screen.queryByRole('button', { name: /Синхронізувати/ })).not.toBeInTheDocument();
  });

  it('показує синхронізацію тому, хто має право на запис', async () => {
    showList(['calls:read', 'calls:write']);

    expect(await screen.findByRole('button', { name: /Синхронізувати/ })).toBeInTheDocument();
  });

  it('відмовляє в розділі тому, хто не має права читати', () => {
    showList(['contacts:read']);

    expect(screen.getByText('Недостатньо прав')).toBeInTheDocument();
  });
});

describe('Журнал дзвінків — недоступний провайдер', () => {
  // The provider is reachable only through the sync action: its being down
  // says nothing about the records already pulled.
  it('називає недоступного провайдера, не ховаючи журнал', async () => {
    showList(['calls:read', 'calls:write']);
    vi.mocked(http.post).mockRejectedValue(
      new ApiError({ status: 502, code: 'CALL_PROVIDER_UNAVAILABLE', message: 'unavailable' }),
    );

    fireEvent.click(await screen.findByRole('button', { name: /Синхронізувати/ }));

    expect(await screen.findByText('Провайдер телефонії недоступний')).toBeInTheDocument();
    // The list is still the list; a failed pull is not an empty screen.
    expect(screen.getByText(/380671234567/)).toBeInTheDocument();
  });

  it('після вдалої синхронізації прибирає попередження про провайдера', async () => {
    showList(['calls:read', 'calls:write']);
    vi.mocked(http.post).mockRejectedValueOnce(
      new ApiError({ status: 502, code: 'CALL_PROVIDER_UNAVAILABLE', message: 'unavailable' }),
    );

    fireEvent.click(await screen.findByRole('button', { name: /Синхронізувати/ }));
    await screen.findByText('Провайдер телефонії недоступний');

    vi.mocked(http.post).mockResolvedValue({ fetched: 4, created: 0, skipped: 4 });
    fireEvent.click(screen.getByRole('button', { name: /Синхронізувати/ }));

    await waitFor(() => {
      expect(screen.queryByText('Провайдер телефонії недоступний')).not.toBeInTheDocument();
    });
  });
});

describe('Журнал дзвінків — синхронізація під звуженою областю', () => {
  // A pull under scope OWN creates calls that are nobody's, and a call that is
  // nobody's is outside this viewer's scope entirely. The server reports
  // records created while the list does not move; unexplained, that reads as a
  // broken sync and invites pressing the button again.
  it('пояснює, чому після синхронізації список не поповнився', async () => {
    showList(['calls:read', 'calls:write'], 'OWN');
    vi.mocked(http.post).mockResolvedValue({ fetched: 9, created: 4, skipped: 5 });

    fireEvent.click(await screen.findByRole('button', { name: /Синхронізувати/ }));

    expect(
      await screen.findByText('Синхронізація додала дзвінків: 4. У вашому списку їх немає'),
    ).toBeInTheDocument();
  });

  it('нічого такого не каже тому, хто бачить весь журнал', async () => {
    showList(['calls:read', 'calls:write'], 'ALL');
    vi.mocked(http.post).mockResolvedValue({ fetched: 9, created: 4, skipped: 5 });

    fireEvent.click(await screen.findByRole('button', { name: /Синхронізувати/ }));

    await waitFor(() => {
      expect(screen.queryByText(/У вашому списку їх немає/)).not.toBeInTheDocument();
    });
  });
});

describe('Журнал дзвінків — збірка API без цього розділу', () => {
  it('пояснює відсутній розділ, а не показує помилку', async () => {
    vi.mocked(http.get).mockRejectedValue(
      new ApiError({ status: 404, code: 'NOT_FOUND', message: 'Not Found' }),
    );

    showList(['calls:read', 'calls:write']);

    expect(await screen.findByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    // Nothing to synchronise in a section the server does not serve.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Синхронізувати/ })).not.toBeInTheDocument();
    });
  });
});
