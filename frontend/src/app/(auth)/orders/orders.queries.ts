'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Money } from '@/lib/money';
import type { Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import { OrdersService } from './orders.service';
import type {
  AddOrderItemInput,
  CreateOrderInput,
  Order,
  OrderListQuery,
  TransitionOrderInput,
  UpdateOrderInput,
  UpdateOrderItemInput,
} from './orders.types';

export const ordersKeys = {
  all: ['orders'] as const,
  lists: () => [...ordersKeys.all, 'list'] as const,
  list: (params: OrderListQuery) => [...ordersKeys.lists(), params] as const,
  details: () => [...ordersKeys.all, 'detail'] as const,
  detail: (id: Id) => [...ordersKeys.details(), id] as const,
};

export const useOrders = (query: OrderListQuery) =>
  useQuery<Page<Order>>({
    queryKey: ordersKeys.list(query),
    queryFn: ({ signal }) => OrdersService.list(query, signal),
    // Paging swaps one page for the next in place instead of blanking the table.
    placeholderData: keepPreviousData,
  });

export const useOrder = (id: Id) =>
  useQuery<Order>({
    queryKey: ordersKeys.detail(id),
    queryFn: ({ signal }) => OrdersService.getById(id, signal),
    enabled: id !== '',
  });

/** An order is known by its number; the total tells two of them apart. */
export const orderLabel = (order: Order): string =>
  `${order.orderNumber} — ${Money.parse(order.total, order.currency).format({ showCurrency: true })}`;

/** One page is what a picker shows; the term narrows it on the server. */
const REFERENCE_PAGE_SIZE = 20;

/** Feeds a reference picker: the search is the one the list page performs. */
export const useOrderOptions = (
  search: string,
): { items: readonly Order[]; isFetching: boolean } => {
  const { data, isFetching } = useOrders({
    page: 1,
    pageSize: REFERENCE_PAGE_SIZE,
    sortBy: 'createdAt',
    sortOrder: 'desc',
    ...(search ? { search } : {}),
  });

  return { items: data?.items ?? [], isFetching };
};

export const useResolvedOrder = (id: Id | undefined): Order | undefined => useOrder(id ?? '').data;

export const useCreateOrder = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateOrderInput) => OrdersService.create(input),
    onSuccess: (order) => {
      queryClient.setQueryData(ordersKeys.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: ordersKeys.lists() });
    },
  });
};

/**
 * The copy is a new record, so only the lists are stale; the source order is
 * untouched by the call and its cached entry stays valid.
 */
export const useDuplicateOrder = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => OrdersService.duplicate(id),
    onSuccess: (order) => {
      queryClient.setQueryData(ordersKeys.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: ordersKeys.lists() });
    },
  });
};

export const useUpdateOrder = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateOrderInput) => OrdersService.update(id, input),
    onSuccess: (order) => {
      // The answer already carries the bumped version — caching it means the
      // next write sends the current one without an extra read.
      queryClient.setQueryData(ordersKeys.detail(id), order);
      void queryClient.invalidateQueries({ queryKey: ordersKeys.lists() });
    },
  });
};

/**
 * The three line operations share a tail: each answers with the whole order,
 * totals and version recomputed, so the card is refreshed from the response
 * rather than from a follow-up GET that would race with it.
 */
const useOrderWriter = <TInput>(id: Id, run: (input: TInput) => Promise<Order>) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: run,
    onSuccess: (order) => {
      queryClient.setQueryData(ordersKeys.detail(id), order);
      void queryClient.invalidateQueries({ queryKey: ordersKeys.lists() });
    },
  });
};

export const useAddOrderItem = (id: Id) =>
  useOrderWriter<AddOrderItemInput>(id, (input) => OrdersService.addItem(id, input));

export const useUpdateOrderItem = (id: Id) =>
  useOrderWriter<{ readonly itemId: Id } & UpdateOrderItemInput>(id, ({ itemId, ...input }) =>
    OrdersService.updateItem(id, itemId, input),
  );

export const useRemoveOrderItem = (id: Id) =>
  useOrderWriter<{ readonly itemId: Id; readonly version: number }>(id, ({ itemId, version }) =>
    OrdersService.removeItem(id, itemId, version),
  );

/**
 * A confirmation reserves stock for every line, so the stock and movement
 * lists go stale the moment this succeeds. They are invalidated by prefix
 * rather than imported from the warehouse module, which owns its own keys.
 */
export const useTransitionOrder = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: TransitionOrderInput) => OrdersService.transition(id, input),
    onSuccess: (order) => {
      queryClient.setQueryData(ordersKeys.detail(id), order);
      void queryClient.invalidateQueries({ queryKey: ordersKeys.lists() });
      void queryClient.invalidateQueries({ queryKey: ['stock'] });
      void queryClient.invalidateQueries({ queryKey: ['stock-movements'] });
    },
  });
};

export const useDeleteOrder = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (version: number) => OrdersService.remove(id, version),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ordersKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: ordersKeys.lists() });
    },
  });
};
