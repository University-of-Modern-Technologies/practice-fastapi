import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type * as ApiModule from '@/shared/api';
import { fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';
import NewProductPage from './new/page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/products/new',
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

const fillAndCreate = async (): Promise<void> => {
  renderWithProviders(<NewProductPage />, { permissions: ['products:read', 'products:write'] });
  await screen.findByText('Дані товару');

  fireEvent.change(screen.getByLabelText('Артикул'), { target: { value: 'srv-100' } });
  fireEvent.change(screen.getByLabelText('Назва'), { target: { value: 'Сервер' } });
  fireEvent.change(screen.getByLabelText('Ціна'), { target: { value: '1200,5' } });
  fireEvent.click(screen.getByRole('button', { name: 'Створити' }));
};

beforeEach(() => {
  vi.mocked(http.post).mockReset();
});

describe('Новий товар — валюта організації', () => {
  it('не пропонує вибирати валюту', async () => {
    renderWithProviders(<NewProductPage />, { permissions: ['products:read', 'products:write'] });
    await screen.findByText('Дані товару');

    expect(screen.getByLabelText('Валюта')).toBeDisabled();
    expect(screen.getByText('Валюта організації, задається в налаштуваннях')).toBeInTheDocument();
  });

  // The API fills the organisation's currency in by itself, and refuses any
  // other; a field the operator never set is not sent at all.
  it('створює товар без валюти в запиті', async () => {
    vi.mocked(http.post).mockReturnValue(new Promise(() => undefined));

    await fillAndCreate();

    await waitFor(() => expect(http.post).toHaveBeenCalledTimes(1));
    const body = vi.mocked(http.post).mock.calls[0]?.[1];
    expect(body).toMatchObject({ sku: 'SRV-100', unitPrice: '1200.50' });
    expect(body).not.toHaveProperty('currency');
  });

  it('пояснює відмову за валютою своїми словами', async () => {
    vi.mocked(http.post).mockRejectedValue(
      new ApiError({
        status: 422,
        code: 'CURRENCY_NOT_SUPPORTED',
        message: 'Only the organisation currency is accepted',
        details: { currency: 'EUR', expected: 'UAH' },
      }),
    );

    await fillAndCreate();

    expect(
      await screen.findByText(
        'Ціни в каталозі ведуться лише у валюті організації — іншу валюту не прийнято',
      ),
    ).toBeInTheDocument();
  });
});
