import { http, type Page, type QueryValue } from '@/shared/api';
import { listQuery } from '@/shared/api/query-builder';
import type { ListParams } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import {
  isProductSortField,
  type CreateProductInput,
  type Product,
  type ProductFilter,
  type ProductListQuery,
  type UpdateProductInput,
} from './products.types';

const ROUTES = {
  collection: '/products',
  byId: (id: Id): string => `/products/${id}`,
} as const;

/**
 * Turns the query string state into the shape the API expects. Filters live in
 * the URL as text, so the boolean and the sort column have to be recognised
 * here — an unknown `sortBy` copied from a hand-edited link would otherwise
 * turn the whole page into a 400.
 */
export const toProductListQuery = (params: ListParams<ProductFilter>): ProductListQuery =>
  listQuery(params)
    .text('search')
    .text('category')
    .boolean('isActive')
    .text('minPrice')
    .text('maxPrice')
    .sort(isProductSortField)
    .build<ProductListQuery>();

/**
 * Rebuilt field by field rather than spread: it guarantees `sku` cannot reach a
 * PATCH even if a caller puts it into the object at runtime.
 */
const toUpdateBody = (input: UpdateProductInput): Readonly<Record<string, unknown>> => ({
  version: input.version,
  ...(input.name === undefined ? {} : { name: input.name }),
  ...(input.description === undefined ? {} : { description: input.description }),
  ...(input.category === undefined ? {} : { category: input.category }),
  ...(input.unitPrice === undefined ? {} : { unitPrice: input.unitPrice }),
  ...(input.currency === undefined ? {} : { currency: input.currency }),
  ...(input.isActive === undefined ? {} : { isActive: input.isActive }),
});

export const ProductsService = {
  list: (query: ProductListQuery, signal?: AbortSignal): Promise<Page<Product>> =>
    http.get<Page<Product>>(ROUTES.collection, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  getById: (id: Id, signal?: AbortSignal): Promise<Product> =>
    http.get<Product>(ROUTES.byId(id), { ...(signal ? { signal } : {}) }),

  create: (input: CreateProductInput): Promise<Product> =>
    http.post<Product>(ROUTES.collection, input),

  update: (id: Id, input: UpdateProductInput): Promise<Product> =>
    http.patch<Product>(ROUTES.byId(id), toUpdateBody(input)),

  /** The version travels in the query string here — a DELETE carries no body. */
  remove: (id: Id, version: number): Promise<void> =>
    http.delete<void>(ROUTES.byId(id), { params: { version } }),
};
