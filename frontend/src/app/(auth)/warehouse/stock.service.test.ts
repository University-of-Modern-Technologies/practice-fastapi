import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import { StockService } from './stock.service';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const level = {
  id: 's-1',
  warehouseId: 'w-1',
  productId: 'p-1',
  quantityOnHand: 12,
  quantityReserved: 4,
  quantityAvailable: 8,
  version: 3,
  createdAt: '2026-08-12T10:00:00.000Z',
  updatedAt: '2026-08-12T10:00:00.000Z',
};

const stub = (body: unknown, status = 200) => {
  const fetchMock = vi.fn().mockResolvedValue(json(status, body));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const callOf = (fetchMock: ReturnType<typeof vi.fn>) => {
  const call = fetchMock.mock.calls[0] as [string, RequestInit];
  // A GET carries no body, so it is only decoded when one was actually sent.
  const body = call[1].body === undefined ? null : (JSON.parse(String(call[1].body)) as unknown);
  return { url: call[0], init: call[1], body };
};

describe('StockService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reads stock levels with the low-stock threshold in the query string', async () => {
    const fetchMock = stub({ data: { items: [level], page: 1, pageSize: 20, total: 1 } });

    await StockService.list({ page: 1, pageSize: 20, warehouseId: 'w-1', lowStockThreshold: 5 });

    expect(callOf(fetchMock).url).toBe(
      '/api/v1/warehouse/stock?page=1&pageSize=20&warehouseId=w-1&lowStockThreshold=5',
    );
  });

  it('keeps a zero threshold instead of dropping it as an empty filter', async () => {
    const fetchMock = stub({ data: { items: [], page: 1, pageSize: 20, total: 0 } });

    await StockService.list({ page: 1, pageSize: 20, lowStockThreshold: 0 });

    expect(callOf(fetchMock).url).toBe(
      '/api/v1/warehouse/stock?page=1&pageSize=20&lowStockThreshold=0',
    );
  });

  it('reads one level by warehouse and product', async () => {
    const fetchMock = stub({ data: level });

    await expect(StockService.get('w-1', 'p-1')).resolves.toEqual(level);
    expect(callOf(fetchMock).url).toBe('/api/v1/warehouse/stock/w-1/p-1');
  });

  it.each([
    ['receive', '/api/v1/warehouse/stock/receive'],
    ['issue', '/api/v1/warehouse/stock/issue'],
    ['reserve', '/api/v1/warehouse/stock/reserve'],
    ['release', '/api/v1/warehouse/stock/release'],
  ] as const)('posts a %s to its own path', async (operation, path) => {
    const fetchMock = stub({ data: level });

    await StockService.run({
      operation,
      input: {
        warehouseId: 'w-1',
        productId: 'p-1',
        quantity: 5,
        referenceType: 'order',
        referenceId: 'o-1',
      },
    });

    const { url, init } = callOf(fetchMock);
    expect(url).toBe(path);
    expect(init.method).toBe('POST');
  });

  it('sends a signed delta and the mandatory note when adjusting', async () => {
    const fetchMock = stub({ data: level });

    await StockService.run({
      operation: 'adjust',
      input: { warehouseId: 'w-1', productId: 'p-1', delta: -3, note: 'Бій під час приймання' },
    });

    const { url, body } = callOf(fetchMock);
    expect(url).toBe('/api/v1/warehouse/stock/adjust');
    expect(body).toEqual({
      warehouseId: 'w-1',
      productId: 'p-1',
      delta: -3,
      note: 'Бій під час приймання',
    });
  });

  it('carries the reservation flag through on an issue against a reservation', async () => {
    const fetchMock = stub({ data: level });

    await StockService.run({
      operation: 'issue',
      input: {
        warehouseId: 'w-1',
        productId: 'p-1',
        quantity: 2,
        fromReservation: true,
        referenceType: 'order',
        referenceId: 'o-1',
      },
    });

    expect(callOf(fetchMock).body).toMatchObject({ fromReservation: true, referenceId: 'o-1' });
  });

  it('surfaces a refused operation as an ApiError carrying its code', async () => {
    stub({ error: { code: 'INSUFFICIENT_STOCK', message: 'Not enough stock' } }, 409);

    const error = await StockService.run({
      operation: 'issue',
      input: { warehouseId: 'w-1', productId: 'p-1', quantity: 99 },
    }).catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'INSUFFICIENT_STOCK' });
  });
});
