import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListParams } from '@/shared/hooks';
import { ProductsService, toProductListQuery } from './products.service';
import type { ProductFilter, UpdateProductInput } from './products.types';

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

const listParams = (
  overrides: Partial<ListParams<ProductFilter>> = {},
): ListParams<ProductFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<ProductFilter>;

describe('toProductListQuery', () => {
  it('leaves out the filters the user has not set', () => {
    expect(toProductListQuery(listParams())).toEqual({ page: 1, pageSize: 20 });
  });

  it('turns the textual active filter into a boolean', () => {
    expect(toProductListQuery(listParams({ isActive: 'false' }))).toMatchObject({
      isActive: false,
    });
    expect(toProductListQuery(listParams({ isActive: 'true' }))).toMatchObject({ isActive: true });
  });

  it('drops a sort column the API does not accept', () => {
    // A hand-edited link must narrow nothing rather than turn the page into a 400.
    const query = toProductListQuery(listParams({ sortBy: 'price', sortOrder: 'asc' }));

    expect(query.sortBy).toBeUndefined();
    expect(query.sortOrder).toBe('asc');
  });

  it('keeps a known sort column', () => {
    expect(toProductListQuery(listParams({ sortBy: 'unitPrice' })).sortBy).toBe('unitPrice');
  });
});

describe('ProductsService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads the list with the query as request parameters', async () => {
    await ProductsService.list({ page: 2, pageSize: 50, search: 'wid' });

    expect(get).toHaveBeenCalledWith('/products', {
      params: { page: 2, pageSize: 50, search: 'wid' },
    });
  });

  it('creates a product at the collection route', async () => {
    const input = { sku: 'SKU-1', name: 'Widget', unitPrice: '19.99' };

    await ProductsService.create(input);

    expect(post).toHaveBeenCalledWith('/products', input);
  });

  it('never sends the sku in a patch', async () => {
    const input = { version: 3, name: 'Widget', sku: 'SKU-2' } as unknown as UpdateProductInput;

    await ProductsService.update('p-1', input);

    expect(patch).toHaveBeenCalledWith('/products/p-1', { version: 3, name: 'Widget' });
  });

  it('keeps an explicit null in a patch, so a field can be cleared', async () => {
    await ProductsService.update('p-1', { version: 1, description: null, category: null });

    expect(patch).toHaveBeenCalledWith('/products/p-1', {
      version: 1,
      description: null,
      category: null,
    });
  });

  it('sends the read version with a delete', async () => {
    await ProductsService.remove('p-1', 7);

    expect(remove).toHaveBeenCalledWith('/products/p-1', { params: { version: 7 } });
  });
});
