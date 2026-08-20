'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Page } from '@/shared/api';
import { DEAL_STAGE } from '@/shared/constants';
import type { Id } from '@/types/domain';
import { DealsService } from './deals.service';
import type {
  CreateDealInput,
  Deal,
  DealListQuery,
  TransitionDealInput,
  UpdateDealInput,
} from './deals.types';

/**
 * Hierarchical keys let a write invalidate exactly what it touched: saving one
 * deal refreshes the lists and that one card, not every cached answer.
 */
export const dealsKeys = {
  all: ['deals'] as const,
  lists: () => [...dealsKeys.all, 'list'] as const,
  list: (params: DealListQuery) => [...dealsKeys.lists(), params] as const,
  details: () => [...dealsKeys.all, 'detail'] as const,
  detail: (id: Id) => [...dealsKeys.details(), id] as const,
};

export const useDeals = (query: DealListQuery) =>
  useQuery<Page<Deal>>({
    queryKey: dealsKeys.list(query),
    queryFn: ({ signal }) => DealsService.list(query, signal),
    // Paging swaps one page for the next in place instead of blanking the table.
    placeholderData: keepPreviousData,
  });

export const useDeal = (id: Id) =>
  useQuery<Deal>({
    queryKey: dealsKeys.detail(id),
    queryFn: ({ signal }) => DealsService.getById(id, signal),
    enabled: id !== '',
  });

/** A deal is recognised by its title plus the stage it currently sits in. */
export const dealLabel = (deal: Deal): string =>
  `${deal.title} — ${DEAL_STAGE[deal.stage]?.label ?? deal.stage}`;

/** One page is what a picker shows; the term narrows it on the server. */
const REFERENCE_PAGE_SIZE = 20;

/** Feeds a reference picker: the search is the one the list page performs. */
export const useDealOptions = (search: string): { items: readonly Deal[]; isFetching: boolean } => {
  const { data, isFetching } = useDeals({
    page: 1,
    pageSize: REFERENCE_PAGE_SIZE,
    sortBy: 'updatedAt',
    sortOrder: 'desc',
    ...(search ? { search } : {}),
  });

  return { items: data?.items ?? [], isFetching };
};

export const useResolvedDeal = (id: Id | undefined): Deal | undefined => useDeal(id ?? '').data;

export const useCreateDeal = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateDealInput) => DealsService.create(input),
    onSuccess: (deal) => {
      queryClient.setQueryData(dealsKeys.detail(deal.id), deal);
      void queryClient.invalidateQueries({ queryKey: dealsKeys.lists() });
    },
  });
};

export const useUpdateDeal = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateDealInput) => DealsService.update(id, input),
    onSuccess: (deal) => {
      // The answer already carries the bumped version — caching it means the
      // next save sends the current one without an extra read.
      queryClient.setQueryData(dealsKeys.detail(id), deal);
      void queryClient.invalidateQueries({ queryKey: dealsKeys.lists() });
    },
  });
};

export const useTransitionDeal = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: TransitionDealInput) => DealsService.transition(id, input),
    onSuccess: (deal) => {
      queryClient.setQueryData(dealsKeys.detail(id), deal);
      void queryClient.invalidateQueries({ queryKey: dealsKeys.lists() });
    },
  });
};

export const useDeleteDeal = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (version: number) => DealsService.remove(id, version),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: dealsKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: dealsKeys.lists() });
    },
  });
};
