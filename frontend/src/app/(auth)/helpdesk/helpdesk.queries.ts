'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import { HelpdeskService } from './helpdesk.service';
import type {
  CreateTicketInput,
  Ticket,
  TicketListQuery,
  TransitionTicketInput,
  UpdateTicketInput,
} from './helpdesk.types';

/**
 * Hierarchical keys let a write invalidate exactly what it touched: saving one
 * ticket refreshes the lists and that one card, not every cached answer.
 *
 * The live channel invalidates through these same factories — the resolver for
 * a `ticket.*` event reads them rather than spelling the keys out a second
 * time, which is what keeps an event and a local save refreshing the same
 * entries.
 */
export const helpdeskKeys = {
  all: ['helpdesk'] as const,
  lists: () => [...helpdeskKeys.all, 'list'] as const,
  list: (params: TicketListQuery) => [...helpdeskKeys.lists(), params] as const,
  details: () => [...helpdeskKeys.all, 'detail'] as const,
  detail: (id: Id) => [...helpdeskKeys.details(), id] as const,
};

export const useTickets = (query: TicketListQuery) =>
  useQuery<Page<Ticket>>({
    queryKey: helpdeskKeys.list(query),
    queryFn: ({ signal }) => HelpdeskService.list(query, signal),
    // Paging swaps one page for the next in place instead of blanking the table.
    placeholderData: keepPreviousData,
  });

export const useTicket = (id: Id) =>
  useQuery<Ticket>({
    queryKey: helpdeskKeys.detail(id),
    queryFn: ({ signal }) => HelpdeskService.getById(id, signal),
    enabled: id !== '',
  });

/** A ticket is recognised by its number plus the subject it was raised about. */
export const ticketLabel = (ticket: Ticket): string => `${ticket.number} — ${ticket.subject}`;

/** One page is what a picker shows; the term narrows it on the server. */
const REFERENCE_PAGE_SIZE = 20;

/** Feeds a reference picker: the search is the one the list page performs. */
export const useTicketOptions = (
  search: string,
): { items: readonly Ticket[]; isFetching: boolean } => {
  const { data, isFetching } = useTickets({
    page: 1,
    pageSize: REFERENCE_PAGE_SIZE,
    sortBy: 'updatedAt',
    sortOrder: 'desc',
    ...(search ? { search } : {}),
  });

  return { items: data?.items ?? [], isFetching };
};

export const useResolvedTicket = (id: Id | undefined): Ticket | undefined =>
  useTicket(id ?? '').data;

export const useCreateTicket = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateTicketInput) => HelpdeskService.create(input),
    onSuccess: (ticket) => {
      queryClient.setQueryData(helpdeskKeys.detail(ticket.id), ticket);
      void queryClient.invalidateQueries({ queryKey: helpdeskKeys.lists() });
    },
  });
};

export const useUpdateTicket = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateTicketInput) => HelpdeskService.update(id, input),
    onSuccess: (ticket) => {
      // The answer already carries the bumped version — caching it means the
      // next save sends the current one without an extra read.
      queryClient.setQueryData(helpdeskKeys.detail(id), ticket);
      void queryClient.invalidateQueries({ queryKey: helpdeskKeys.lists() });
    },
  });
};

export const useTransitionTicket = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: TransitionTicketInput) => HelpdeskService.transition(id, input),
    onSuccess: (ticket) => {
      queryClient.setQueryData(helpdeskKeys.detail(id), ticket);
      void queryClient.invalidateQueries({ queryKey: helpdeskKeys.lists() });
    },
  });
};

export const useDeleteTicket = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (version: number) => HelpdeskService.remove(id, version),
    onSuccess: () => {
      // The record is gone; keeping its card cached would show a ghost.
      queryClient.removeQueries({ queryKey: helpdeskKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: helpdeskKeys.lists() });
    },
  });
};
