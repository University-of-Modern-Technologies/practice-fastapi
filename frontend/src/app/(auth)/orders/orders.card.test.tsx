import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OrderStatus } from '@/shared/constants';
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
import OrderPage from './[id]/page';
import OrdersPage from './page';
import type { Order } from './orders.types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/orders/1',
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

const ORDER_ID = '22222222-2222-2222-2222-222222222222';

const order = (status: OrderStatus): Order => ({
  id: ORDER_ID,
  orderNumber: 'ORD-1042',
  ownerId: '00000000-0000-0000-0000-000000000001',
  contactId: null,
  dealId: null,
  status,
  currency: 'USD',
  subtotal: '300.00',
  discountTotal: '0.00',
  taxTotal: '0.00',
  total: '300.00',
  notes: null,
  placedAt: null,
  version: 4,
  createdAt: '2026-08-01T10:00:00.000Z',
  updatedAt: '2026-08-10T10:00:00.000Z',
  items: [
    {
      id: 'item-1',
      orderId: ORDER_ID,
      productId: '33333333-3333-3333-3333-333333333333',
      sku: 'SRV-100',
      name: 'Сервер',
      quantity: 3,
      unitPrice: '100.00',
      lineTotal: '300.00',
      createdAt: '2026-08-01T10:00:00.000Z',
      updatedAt: '2026-08-01T10:00:00.000Z',
    },
  ],
});

const conflict = (code: string): ApiError =>
  new ApiError({ status: 409, code, message: 'Конфлікт' });

const showCard = (status: OrderStatus, permissions: readonly string[]): void => {
  vi.mocked(http.get).mockResolvedValue(order(status));
  renderWithProviders(<OrderPage params={routeParams({ id: ORDER_ID })} />, { permissions });
};

const openCard = async (status: OrderStatus): Promise<void> => {
  showCard(status, ['orders:read', 'orders:write']);
  await screen.findByText('Замовлення ORD-1042');
};

/** Opens the status dialog and confirms it. */
const moveStatus = async (label: string): Promise<void> => {
  fireEvent.click(screen.getByRole('button', { name: /Змінити статус/ }));

  // The dialog's own button carries the same name as the one that opened it.
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getByRole('radio', { name: label }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Змінити статус' }));
};

beforeEach(() => {
  vi.mocked(http.post).mockReset();
  vi.mocked(http.patch).mockReset();
});

describe('Картка замовлення — редагованість', () => {
  it('чернетку дає правити: позиції додаються, кількість вводиться', async () => {
    await openCard('DRAFT');

    expect(screen.getAllByRole('button', { name: 'Додати позицію' }).length).toBeGreaterThan(0);
    expect(screen.getByRole('spinbutton')).toBeInTheDocument();
    expect(
      screen.queryByText('Замовлення вже підтверджено — позиції не змінюються'),
    ).not.toBeInTheDocument();
  });

  it('підтверджене замовлення не пропонує ані позицій, ані сум', async () => {
    await openCard('CONFIRMED');

    expect(
      screen.getByText('Замовлення вже підтверджено — позиції не змінюються'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Додати позицію' })).not.toBeInTheDocument();
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Знижка')).toBeDisabled();
    expect(screen.getByLabelText('Валюта')).toBeDisabled();
  });
});

describe('Картка замовлення — переходи статусу', () => {
  it('пропонує лише ті статуси, які дозволяє машина станів', async () => {
    await openCard('DRAFT');
    fireEvent.click(screen.getByRole('button', { name: /Змінити статус/ }));

    expect(await screen.findByRole('radio', { name: 'Підтверджено' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Скасовано' })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'Виконано' })).not.toBeInTheDocument();
  });

  it('не пропонує зміну статусу для виконаного замовлення', async () => {
    await openCard('FULFILLED');

    expect(screen.queryByRole('button', { name: /Змінити статус/ })).not.toBeInTheDocument();
  });
});

describe('Картка замовлення — два значення 409', () => {
  it('пропонує перечитати запис, коли замовлення змінив хтось інший', async () => {
    await openCard('DRAFT');
    vi.mocked(http.post).mockRejectedValue(conflict('ORDER_CONCURRENT_MODIFICATION'));

    await moveStatus('Підтверджено');

    expect(await screen.findByText('Запис змінив інший користувач')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Перечитати' })).toBeInTheDocument();
  });

  // Stock is not a lost race: re-reading the order changes nothing, so the page
  // has to name the reason the warehouse refused instead of offering a reload.
  it('пояснює брак залишку замість пропозиції перечитати', async () => {
    await openCard('DRAFT');
    vi.mocked(http.post).mockRejectedValue(conflict('INSUFFICIENT_STOCK'));

    await moveStatus('Підтверджено');

    expect(await screen.findByText('Недостатньо залишку для підтвердження')).toBeInTheDocument();
    expect(screen.queryByText('Запис змінив інший користувач')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Перечитати' })).not.toBeInTheDocument();
  });

  it('пояснює відмову домену, коли позицію правлять у вже підтвердженому замовленні', async () => {
    await openCard('DRAFT');
    vi.mocked(http.patch).mockRejectedValue(conflict('ORDER_NOT_EDITABLE'));

    const quantity = screen.getByRole('spinbutton');
    fireEvent.change(quantity, { target: { value: '5' } });
    fireEvent.blur(quantity);

    expect(
      await screen.findByText('Замовлення вже підтверджено — позиції не змінюються'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Запис змінив інший користувач')).not.toBeInTheDocument();
  });
});

describe('Список замовлень — дозволи', () => {
  const showList = (permissions: readonly string[]): void => {
    vi.mocked(http.get).mockResolvedValue({
      items: [order('DRAFT')],
      page: 1,
      pageSize: 20,
      total: 1,
    });
    renderWithProviders(<OrdersPage />, { permissions });
  };

  it('показує список і кнопку створення тому, хто має право запису', async () => {
    showList(['orders:read', 'orders:write']);

    expect(await screen.findByText('ORD-1042')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Створити замовлення' }).length).toBeGreaterThan(
      0,
    );
  });

  it('читачеві показує список без кнопки створення', async () => {
    showList(['orders:read']);

    expect(await screen.findByText('ORD-1042')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Створити замовлення' })).not.toBeInTheDocument();
  });
});

describe('Картка замовлення — дозволи', () => {
  it('читачеві не пропонує ані зміни статусу, ані правки позицій', async () => {
    showCard('DRAFT', ['orders:read']);
    await screen.findByText('Замовлення ORD-1042');

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Змінити статус/ })).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Додати позицію' })).not.toBeInTheDocument();
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
  });
});

describe('Картка замовлення — повторення', () => {
  const copy = { ...order('DRAFT'), id: 'copy-1', orderNumber: 'ORD-1043', version: 1 };

  it('повторює замовлення, не чіпаючи джерело', async () => {
    await openCard('FULFILLED');
    vi.mocked(http.post).mockResolvedValue(copy);

    fireEvent.click(screen.getByRole('button', { name: /Повторити/ }));

    await waitFor(() => {
      expect(http.post).toHaveBeenCalledWith(`/orders/${ORDER_ID}/duplicate`, undefined);
    });
    // No version travels with the call: a copy cannot lose a race with an edit
    // to the order it was made from.
    expect(vi.mocked(http.patch)).not.toHaveBeenCalled();
  });

  // The copy is a draft that still needs checking, and staying on the source
  // would hide that a record was created at all.
  it('повідомляє номер створеної копії', async () => {
    await openCard('FULFILLED');
    vi.mocked(http.post).mockResolvedValue(copy);

    fireEvent.click(screen.getByRole('button', { name: /Повторити/ }));

    expect(await screen.findByText('Створено замовлення ORD-1043')).toBeInTheDocument();
  });

  it('пояснює відмову, коли товар уже знято з продажу', async () => {
    await openCard('FULFILLED');
    vi.mocked(http.post).mockRejectedValue(conflict('PRODUCT_INACTIVE'));

    fireEvent.click(screen.getByRole('button', { name: /Повторити/ }));

    expect(
      await screen.findByText('Товар вимкнено — його не можна додати до замовлення'),
    ).toBeInTheDocument();
  });

  it('пропонує повторення й для скасованого замовлення', async () => {
    await openCard('CANCELLED');

    expect(screen.getByRole('button', { name: /Повторити/ })).toBeInTheDocument();
  });

  it('читачеві повторення не пропонує', async () => {
    showCard('FULFILLED', ['orders:read']);
    await screen.findByText('Замовлення ORD-1042');

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Повторити/ })).not.toBeInTheDocument();
    });
  });
});
