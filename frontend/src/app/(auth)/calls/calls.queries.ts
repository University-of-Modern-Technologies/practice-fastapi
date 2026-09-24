'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import { CallsService } from './calls.service';
import type {
  Call,
  CallListQuery,
  CallRecording,
  CallSyncResult,
  LinkCallInput,
  UpdateCallInput,
} from './calls.types';

/**
 * Hierarchical keys let a write invalidate exactly what it touched: linking one
 * call refreshes the lists and that one card, not every cached answer.
 *
 * The live channel is meant to invalidate through these same factories — the
 * resolver for a `call.*` event reads them rather than spelling the keys out a
 * second time, which is what keeps an event and a local save refreshing the
 * same entries. Wiring `call.created`, `call.updated`, `call.linked` and
 * `call.deleted` into that resolver belongs to whoever owns the shared realtime
 * layer; this module only publishes the keys.
 */
export const callsKeys = {
  all: ['calls'] as const,
  lists: () => [...callsKeys.all, 'list'] as const,
  list: (params: CallListQuery) => [...callsKeys.lists(), params] as const,
  details: () => [...callsKeys.all, 'detail'] as const,
  detail: (id: Id) => [...callsKeys.details(), id] as const,
};

export const useCalls = (query: CallListQuery) =>
  useQuery<Page<Call>>({
    queryKey: callsKeys.list(query),
    queryFn: ({ signal }) => CallsService.list(query, signal),
    // Paging swaps one page for the next in place instead of blanking the table.
    placeholderData: keepPreviousData,
  });

export const useCall = (id: Id) =>
  useQuery<Call>({
    queryKey: callsKeys.detail(id),
    queryFn: ({ signal }) => CallsService.getById(id, signal),
    enabled: id !== '',
  });

/**
 * Pulling a batch from the provider. It is a mutation rather than a query even
 * though it reads from somewhere else: it creates records, and it must happen
 * when the operator asks for it and not because a component mounted.
 */
export const useSyncCalls = () => {
  const queryClient = useQueryClient();

  return useMutation<CallSyncResult, unknown, void>({
    mutationFn: () => CallsService.sync(),
    onSuccess: (result) => {
      // Nothing new means nothing to re-read: a refetch after every empty pull
      // would restart the open table for no change at all.
      if (result.created > 0) void queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
    },
  });
};

export const useUpdateCall = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateCallInput) => CallsService.update(id, input),
    onSuccess: (call) => {
      // The answer already carries the bumped version — caching it means the
      // next save sends the current one without an extra read.
      queryClient.setQueryData(callsKeys.detail(id), call);
      void queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
    },
  });
};

export const useLinkCall = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: LinkCallInput) => CallsService.link(id, input),
    onSuccess: (call) => {
      queryClient.setQueryData(callsKeys.detail(id), call);
      // The list carries the `hasContact` filter, so a link can move a row out
      // of the view it was just acted on in.
      void queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
    },
  });
};

export const useDeleteCall = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (version: number) => CallsService.remove(id, version),
    onSuccess: () => {
      // The record is gone; keeping its card cached would show a ghost.
      queryClient.removeQueries({ queryKey: callsKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
    },
  });
};

/**
 * Asks for the address of the recording. Deliberately a mutation and not a
 * query: the answer expires, and anything the cache kept would be handed back
 * to the next caller as if it were still good. Every request is a fresh one,
 * made at the moment somebody actually wants to listen.
 */
export const useCallRecording = (id: Id) =>
  useMutation<CallRecording, unknown, void>({
    mutationFn: () => CallsService.recording(id),
  });
