import { ORDER_STATUSES } from '@/shared/constants';
import { http, type Page, type QueryValue } from '@/shared/api';
import { listQuery } from '@/shared/api/query-builder';
import type { ListParams } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import {
  isOrderSortField,
  type AddOrderItemInput,
  type CreateOrderInput,
  type Order,
  type OrderFilter,
  type OrderListQuery,
  type TransitionOrderInput,
  type UpdateOrderInput,
  type UpdateOrderItemInput,
} from './orders.types';

const ROUTES = {
  collection: '/orders',
  byId: (id: Id): string => `/orders/${id}`,
  duplicate: (id: Id): string => `/orders/${id}/duplicate`,
  items: (id: Id): string => `/orders/${id}/items`,
  item: (id: Id, itemId: Id): string => `/orders/${id}/items/${itemId}`,
  transitions: (id: Id): string => `/orders/${id}/transitions`,
} as const;

const ORDER_SEARCH_MAX_LENGTH = 64;

/**
 * Turns the query string state into the shape the API expects. Filters live in
 * the URL as text, so the status and the sort column have to be recognised
 * here — an unknown value copied from a hand-edited link would otherwise turn
 * the whole page into a 400 instead of narrowing nothing.
 */
export const toOrderListQuery = (params: ListParams<OrderFilter>): OrderListQuery =>
  listQuery(params)
    .text('search', { maxLength: ORDER_SEARCH_MAX_LENGTH })
    .text('ownerId')
    .text('contactId')
    .text('dealId')
    .oneOf('status', ORDER_STATUSES)
    .text('minTotal')
    .text('maxTotal')
    .sort(isOrderSortField)
    .build<OrderListQuery>();

/**
 * Rebuilt field by field rather than spread: it guarantees a total, a status or
 * an order number cannot reach a PATCH even if a caller puts one into the
 * object at runtime. The server derives all four and rejects them on input.
 */
const toUpdateBody = (input: UpdateOrderInput): Readonly<Record<string, unknown>> => ({
  version: input.version,
  ...(input.ownerId === undefined ? {} : { ownerId: input.ownerId }),
  ...(input.contactId === undefined ? {} : { contactId: input.contactId }),
  ...(input.dealId === undefined ? {} : { dealId: input.dealId }),
  ...(input.currency === undefined ? {} : { currency: input.currency }),
  ...(input.discountTotal === undefined ? {} : { discountTotal: input.discountTotal }),
  ...(input.taxTotal === undefined ? {} : { taxTotal: input.taxTotal }),
  ...(input.notes === undefined ? {} : { notes: input.notes }),
});

/**
 * The only place that knows the shape of the order endpoints. It holds no
 * React, so its request paths and bodies can be asserted without a DOM.
 *
 * All three line operations answer with the whole order, version included —
 * the caller caches that answer instead of re-reading the record.
 */
export const OrdersService = {
  list: (query: OrderListQuery, signal?: AbortSignal): Promise<Page<Order>> =>
    http.get<Page<Order>>(ROUTES.collection, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  getById: (id: Id, signal?: AbortSignal): Promise<Order> =>
    http.get<Order>(ROUTES.byId(id), { ...(signal ? { signal } : {}) }),

  create: (input: CreateOrderInput): Promise<Order> => http.post<Order>(ROUTES.collection, input),

  /**
   * Copies an order into a fresh draft. The lines are re-priced from the
   * catalogue on the server, so the answer is a new order rather than the one
   * that was copied — nothing about the source changes.
   */
  duplicate: (id: Id): Promise<Order> => http.post<Order>(ROUTES.duplicate(id), undefined),

  update: (id: Id, input: UpdateOrderInput): Promise<Order> =>
    http.patch<Order>(ROUTES.byId(id), toUpdateBody(input)),

  addItem: (id: Id, input: AddOrderItemInput): Promise<Order> =>
    http.post<Order>(ROUTES.items(id), input),

  updateItem: (id: Id, itemId: Id, input: UpdateOrderItemInput): Promise<Order> =>
    http.patch<Order>(ROUTES.item(id, itemId), input),

  /** The version travels in the query string here — a DELETE carries no body. */
  removeItem: (id: Id, itemId: Id, version: number): Promise<Order> =>
    http.delete<Order>(ROUTES.item(id, itemId), { params: { version } }),

  /** The status only ever moves through this route, never through a PATCH. */
  transition: (id: Id, input: TransitionOrderInput): Promise<Order> =>
    http.post<Order>(ROUTES.transitions(id), input),

  remove: (id: Id, version: number): Promise<void> =>
    http.delete<void>(ROUTES.byId(id), { params: { version } }),
};
