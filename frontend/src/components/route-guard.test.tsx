import { describe, expect, it, vi } from 'vitest';
import type * as ApiModule from '@/shared/api';
import { resumeSession } from '@/shared/auth';
import { useAuthStore } from '@/shared/stores';
import { act, fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';
import { RouteGuard } from './route-guard';

const replace = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace, back: vi.fn() }),
  usePathname: () => '/deals',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return { ...actual, restoreSession: vi.fn() };
});

const { ApiError, restoreSession } = await import('@/shared/api');

const unavailable = (): InstanceType<typeof ApiError> =>
  new ApiError({ status: 503, code: 'HTTP_503', message: 'Service Unavailable' });

describe('resumeSession', () => {
  it('робить холодний вхід без cookie анонімним', async () => {
    vi.mocked(restoreSession).mockResolvedValueOnce(null);

    await resumeSession();

    expect(useAuthStore.getState().status).toBe('anonymous');
  });

  // The old probe had no `catch`: a 5xx left the status at `unknown`, and the
  // shell drew its skeleton forever.
  it('не лишає застосунок у завантаженні, коли сервер не відповів', async () => {
    useAuthStore.getState().markChecking();
    vi.mocked(restoreSession).mockRejectedValueOnce(unavailable());

    await resumeSession();

    expect(useAuthStore.getState().status).toBe('unreachable');
  });
});

describe('RouteGuard', () => {
  it('пропонує спробувати ще раз замість входу, коли сесію не вдалося перевірити', async () => {
    renderWithProviders(
      <RouteGuard>
        <p>Розділ</p>
      </RouteGuard>,
    );
    // The harness starts anonymous; only what happens after the failed probe counts.
    act(() => useAuthStore.getState().markUnreachable());
    replace.mockClear();
    vi.mocked(restoreSession).mockRejectedValueOnce(unavailable());

    fireEvent.click(await screen.findByRole('button', { name: 'Спробувати ще' }));

    await waitFor(() => expect(restoreSession).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Не вдалося перевірити сесію')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalledWith(expect.stringContaining('/login'));
  });
});
