import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListParams } from '@/shared/hooks';
import { OrdersService, toOrderListQuery } from './orders.service';
import type { OrderFilter, UpdateOrderInput } from './orders.types';

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const remove = vi.fn();

vi.mock('@/shared/api', () => ({
  http: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    patch: (...args: unknown[]) => patch(...args),
    delete: (...args: unknown[]) => remove(...args),
  },
}));

const listParams = (overrides: Partial<ListParams<OrderFilter>> = {}): ListParams<OrderFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<OrderFilter>;

describe('toOrderListQuery', () => {
  it('leaves out the filters the user has not set', () => {
    expect(toOrderListQuery(listParams())).toEqual({ page: 1, pageSize: 20 });
  });

  it('keeps a known status and drops an invented one', () => {
    expect(toOrderListQuery(listParams({ status: 'CONFIRMED' })).status).toBe('CONFIRMED');
    expect(toOrderListQuery(listParams({ status: 'SHIPPED' })).status).toBeUndefined();
  });

  it('drops a sort column the API does not accept', () => {
    // A hand-edited link must narrow nothing rather than turn the page into a 400.
    const query = toOrderListQuery(listParams({ sortBy: 'subtotal', sortOrder: 'asc' }));

    expect(query.sortBy).toBeUndefined();
    expect(query.sortOrder).toBe('asc');
  });

  it('keeps a known sort column', () => {
    expect(toOrderListQuery(listParams({ sortBy: 'total' })).sortBy).toBe('total');
  });

  it('trims an over-long search term to the length the API accepts', () => {
    const query = toOrderListQuery(listParams({ search: 'x'.repeat(80) }));

    expect(query.search).toHaveLength(64);
  });

  it('passes the total bounds through as the strings they are', () => {
    expect(toOrderListQuery(listParams({ minTotal: '10.00', maxTotal: '99.50' }))).toMatchObject({
      minTotal: '10.00',
      maxTotal: '99.50',
    });
  });
});

describe('OrdersService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads the list with the query as request parameters', async () => {
    await OrdersService.list({ page: 2, pageSize: 50, status: 'DRAFT' });

    expect(get).toHaveBeenCalledWith('/orders', {
      params: { page: 2, pageSize: 50, status: 'DRAFT' },
    });
  });

  it('creates an order at the collection route', async () => {
    const input = { currency: 'USD', items: [{ productId: 'p-1', quantity: 2 }] };

    await OrdersService.create(input);

    expect(post).toHaveBeenCalledWith('/orders', input);
  });

  it('never sends a server-derived field in a patch', async () => {
    const input = {
      version: 3,
      notes: 'нотатка',
      status: 'PAID',
      total: '999.00',
      orderNumber: 'ORD-1',
    } as unknown as UpdateOrderInput;

    await OrdersService.update('o-1', input);

    expect(patch).toHaveBeenCalledWith('/orders/o-1', { version: 3, notes: 'нотатка' });
  });

  it('keeps an explicit null in a patch, so a link can be cleared', async () => {
    await OrdersService.update('o-1', { version: 1, contactId: null, dealId: null });

    expect(patch).toHaveBeenCalledWith('/orders/o-1', {
      version: 1,
      contactId: null,
      dealId: null,
    });
  });

  it('adds a line with the version in the body', async () => {
    await OrdersService.addItem('o-1', { version: 4, productId: 'p-1', quantity: 3 });

    expect(post).toHaveBeenCalledWith('/orders/o-1/items', {
      version: 4,
      productId: 'p-1',
      quantity: 3,
    });
  });

  it('changes a line quantity at the line route', async () => {
    await OrdersService.updateItem('o-1', 'i-1', { version: 5, quantity: 7 });

    expect(patch).toHaveBeenCalledWith('/orders/o-1/items/i-1', { version: 5, quantity: 7 });
  });

  it('sends the read version with a line removal', async () => {
    await OrdersService.removeItem('o-1', 'i-1', 6);

    expect(remove).toHaveBeenCalledWith('/orders/o-1/items/i-1', { params: { version: 6 } });
  });

  it('moves the status through the transitions route, never through a patch', async () => {
    await OrdersService.transition('o-1', { version: 8, status: 'CONFIRMED' });

    expect(post).toHaveBeenCalledWith('/orders/o-1/transitions', {
      version: 8,
      status: 'CONFIRMED',
    });
    expect(patch).not.toHaveBeenCalled();
  });

  it('sends the read version with a delete', async () => {
    await OrdersService.remove('o-1', 9);

    expect(remove).toHaveBeenCalledWith('/orders/o-1', { params: { version: 9 } });
  });
});
