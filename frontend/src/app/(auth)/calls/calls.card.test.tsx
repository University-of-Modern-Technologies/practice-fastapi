import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import {
  fireEvent,
  renderWithProviders,
  routeParams,
  screen,
  waitFor,
  within,
} from '@/test/render';
import CallPage from './[id]/page';
import type { Call, CallRecording } from './calls.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/calls/22222222-2222-2222-2222-222222222222',
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

const CALL_ID = '22222222-2222-2222-2222-222222222222';

const call = (overrides: Partial<Call> = {}): Call => ({
  id: CALL_ID,
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
  version: 3,
  createdAt: '2026-08-12T15:24:00.000Z',
  updatedAt: '2026-08-12T15:24:00.000Z',
  ...overrides,
});

const apiError = (status: number, code: string): ApiError =>
  new ApiError({ status, code, message: 'Відмова' });

/**
 * One call, and whatever the recording endpoint is set to answer. The two share
 * `http.get`, so the reads are told apart by path rather than by call order.
 */
const serve = (record: Call, recording?: CallRecording | ApiError): void => {
  vi.mocked(http.get).mockImplementation((path: string) => {
    if (path.endsWith('/recording')) {
      if (recording === undefined)
        return Promise.reject(apiError(404, 'CALL_RECORDING_UNAVAILABLE'));
      return recording instanceof ApiError
        ? Promise.reject(recording)
        : Promise.resolve(recording as never);
    }
    return Promise.resolve(record as never);
  });
};

const openCard = async (
  permissions: readonly string[] = ['calls:read', 'calls:write'],
): Promise<void> => {
  renderWithProviders(<CallPage params={routeParams({ id: CALL_ID })} />, { permissions });
  await screen.findByRole('heading', { name: /380671234567/ });
};

beforeEach(() => {
  vi.mocked(http.get).mockReset();
  vi.mocked(http.post).mockReset();
  vi.mocked(http.patch).mockReset();
});

describe('Картка дзвінка — порожні звʼязки', () => {
  // A call arrives before anyone has decided who it was with, what it was
  // about, or whose it is. All three being empty at once is the ordinary state
  // of a fresh record, and the card has to read as work waiting, not as a row
  // that lost its data.
  it('називає кожен непривʼязаний звʼязок станом роботи, а не порожнім значенням', async () => {
    serve(call());
    await openCard();

    expect(screen.getByText('Ще не привʼязано до контакту')).toBeInTheDocument();
    expect(screen.getByText('Ще не привʼязано до угоди')).toBeInTheDocument();
    expect(screen.getByText('Дзвінок ще ніхто не взяв')).toBeInTheDocument();
  });

  it('кличе привʼязати дзвінок, поки він ні до чого не привʼязаний', async () => {
    serve(call());
    await openCard();

    expect(screen.getByRole('button', { name: /Привʼязати/ })).toBeInTheDocument();
  });

  it('після привʼязки пропонує змінити її, а не створити ще одну', async () => {
    serve(call({ contactId: '33333333-3333-3333-3333-333333333333' }));
    await openCard();

    expect(screen.getByRole('button', { name: /Змінити привʼязку/ })).toBeInTheDocument();
  });
});

describe('Картка дзвінка — привʼязка як окрема дія', () => {
  // The link endpoint refuses an empty body: at least one reference has to be
  // named, so a dialog with nothing picked never becomes a request.
  it('не надсилає дії, у якій не вибрано ні контакту, ні угоди', async () => {
    serve(call());
    await openCard();

    fireEvent.click(screen.getByRole('button', { name: /Привʼязати/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Привʼязати' }));

    expect(await screen.findByText('Виберіть контакт або угоду')).toBeInTheDocument();
    await waitFor(() => {
      expect(http.post).not.toHaveBeenCalled();
    });
  });

  // Attaching and detaching are two different requests. The dialog only ever
  // attaches — a `null` there is refused — so detaching gets its own control,
  // and it goes out as a PATCH that clears the field.
  it('знімає звʼязок окремим PATCH, а не тією самою дією привʼязки', async () => {
    serve(call({ contactId: '33333333-3333-3333-3333-333333333333' }));
    await openCard();

    vi.mocked(http.patch).mockResolvedValue(call() as never);
    fireEvent.click(screen.getByRole('button', { name: 'Відвʼязати' }));

    await waitFor(() => {
      expect(http.patch).toHaveBeenCalledWith(
        `/calls/${CALL_ID}`,
        expect.objectContaining({ version: 3, contactId: null }),
      );
    });
    expect(http.post).not.toHaveBeenCalled();
  });

  it('не пропонує відвʼязати те, що ще ні до чого не привʼязане', async () => {
    serve(call());
    await openCard();

    expect(screen.queryByRole('button', { name: 'Відвʼязати' })).not.toBeInTheDocument();
  });
});

describe('Картка дзвінка — запис розмови', () => {
  // The recording is asked for when somebody wants to listen: the address
  // expires, so nothing is fetched and held in advance.
  it('не просить адреси запису, поки її не попросили', async () => {
    serve(call(), { url: 'https://recordings.test/a.mp3', expiresAt: '2099-01-01T00:00:00.000Z' });
    await openCard();

    expect(http.get).not.toHaveBeenCalledWith(
      expect.stringContaining('/recording'),
      expect.anything(),
    );
    expect(screen.getByRole('button', { name: /Отримати запис/ })).toBeInTheDocument();
  });

  it('показує посилання разом зі строком, до якого воно працює', async () => {
    serve(call(), { url: 'https://recordings.test/a.mp3', expiresAt: '2099-01-01T00:00:00.000Z' });
    await openCard();

    fireEvent.click(screen.getByRole('button', { name: /Отримати запис/ }));

    expect(await screen.findByText('Відкрити запис')).toBeInTheDocument();
    expect(screen.getByText(/Посилання дійсне до/)).toBeInTheDocument();
  });

  // A link past its expiry is a button that fails when pressed. It is replaced
  // by the offer to ask again rather than left on screen looking live.
  it('не лишає на екрані посилання, строк якого вже минув', async () => {
    serve(call(), { url: 'https://recordings.test/a.mp3', expiresAt: '2020-01-01T00:00:00.000Z' });
    await openCard();

    fireEvent.click(screen.getByRole('button', { name: /Отримати запис/ }));

    expect(await screen.findByText('Посилання на запис уже недійсне')).toBeInTheDocument();
    expect(screen.queryByText('Відкрити запис')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Оновити посилання/ })).toBeInTheDocument();
  });

  // "This call has no recording" is an answer about this call, not a failure
  // of the section.
  it('пояснює відсутній запис, не повідомляючи про помилку', async () => {
    serve(call(), apiError(404, 'CALL_RECORDING_UNAVAILABLE'));
    await openCard();

    fireEvent.click(screen.getByRole('button', { name: /Отримати запис/ }));

    expect(await screen.findByText('Запису розмови немає')).toBeInTheDocument();
  });
});

describe('Картка дзвінка — дозволи', () => {
  it('читачеві не пропонує ні привʼязки, ні редагування', async () => {
    serve(call());
    renderWithProviders(<CallPage params={routeParams({ id: CALL_ID })} />, {
      permissions: ['calls:read'],
    });
    await screen.findByRole('heading', { name: /380671234567/ });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Привʼязати/ })).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Зберегти' })).not.toBeInTheDocument();
    expect(screen.getByText('Нотаток до цього дзвінка ще немає')).toBeInTheDocument();
  });
});

describe('Картка дзвінка — чужий запис', () => {
  // A record someone else owns answers 404 rather than 403, so the page must
  // not claim the call was deleted.
  it('не стверджує, що запис видалено, коли він може бути просто чужим', async () => {
    vi.mocked(http.get).mockRejectedValue(apiError(404, 'CALL_NOT_FOUND'));
    renderWithProviders(<CallPage params={routeParams({ id: CALL_ID })} />, {
      permissions: ['calls:read'],
    });

    expect(await screen.findByText('Дзвінок не знайдено')).toBeInTheDocument();
    expect(screen.getByText(/недоступний вашій області доступу/)).toBeInTheDocument();
  });
});
