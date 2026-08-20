import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WarehouseService } from './warehouse.service';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const warehouse = {
  id: 'w-1',
  code: 'MAIN',
  name: 'Головний склад',
  isActive: true,
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
  return { url: call[0], init: call[1] };
};

describe('WarehouseService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reads a page of warehouses with its filters in the query string', async () => {
    const fetchMock = stub({ data: { items: [warehouse], page: 1, pageSize: 20, total: 1 } });

    const page = await WarehouseService.list({
      page: 1,
      pageSize: 20,
      search: 'голов',
      isActive: true,
    });

    expect(callOf(fetchMock).url).toBe(
      '/api/v1/warehouse/warehouses?page=1&pageSize=20&search=%D0%B3%D0%BE%D0%BB%D0%BE%D0%B2&isActive=true',
    );
    expect(page.items).toEqual([warehouse]);
  });

  it('omits filters that were left empty', async () => {
    const fetchMock = stub({ data: { items: [], page: 1, pageSize: 20, total: 0 } });

    await WarehouseService.list({ page: 2, pageSize: 50 });

    expect(callOf(fetchMock).url).toBe('/api/v1/warehouse/warehouses?page=2&pageSize=50');
  });

  it('reads one warehouse by id', async () => {
    const fetchMock = stub({ data: warehouse });

    await expect(WarehouseService.get('w-1')).resolves.toEqual(warehouse);
    expect(callOf(fetchMock).url).toBe('/api/v1/warehouse/warehouses/w-1');
  });

  it('creates a warehouse with the body the API expects', async () => {
    const fetchMock = stub({ data: warehouse }, 201);

    await WarehouseService.create({ code: 'MAIN', name: 'Головний склад', isActive: true });

    const { url, init } = callOf(fetchMock);
    expect(url).toBe('/api/v1/warehouse/warehouses');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      code: 'MAIN',
      name: 'Головний склад',
      isActive: true,
    });
  });

  it('never sends the code on an update, because the API treats it as immutable', async () => {
    const fetchMock = stub({ data: warehouse });

    await WarehouseService.update('w-1', { name: 'Інша назва', isActive: false });

    const { url, init } = callOf(fetchMock);
    expect(url).toBe('/api/v1/warehouse/warehouses/w-1');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({ name: 'Інша назва', isActive: false });
  });
});
