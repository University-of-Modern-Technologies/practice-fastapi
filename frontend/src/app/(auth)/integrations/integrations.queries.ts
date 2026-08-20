'use client';

import {
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import {
  IntegrationsService,
  isModuleUnavailable,
  isShipmentMissing,
} from './integrations.service';
import type {
  CreateShipmentInput,
  DeliveryHealth,
  DeliveryQuote,
  QuoteRequestInput,
  Shipment,
} from './integrations.types';

export const integrationsKeys = {
  all: ['integrations'] as const,
  health: () => [...integrationsKeys.all, 'health'] as const,
  shipments: () => [...integrationsKeys.all, 'shipment'] as const,
  shipment: (id: string) => [...integrationsKeys.shipments(), id] as const,
};

const MAX_ATTEMPTS = 2;

/** A missing section is an answer, not a hiccup: retrying it only delays the notice. */
const retry = (failureCount: number, error: Error): boolean =>
  !isModuleUnavailable(error) && failureCount < MAX_ATTEMPTS;

/** The breaker changes state on its own, so the page watches it instead of snapshotting it. */
const HEALTH_POLL_MS = 15_000;

export const useDeliveryHealth = (): UseQueryResult<DeliveryHealth> =>
  useQuery({
    queryKey: integrationsKeys.health(),
    queryFn: ({ signal }) => IntegrationsService.health(signal),
    // Polling a route this API build does not serve would fail every fifteen
    // seconds forever; once the section is known to be absent, the monitor stops.
    refetchInterval: (query) => (isModuleUnavailable(query.state.error) ? false : HEALTH_POLL_MS),
    refetchIntervalInBackground: false,
    staleTime: 0,
    retry,
  });

export const useCreateQuote = (): UseMutationResult<DeliveryQuote, Error, QuoteRequestInput> =>
  useMutation({
    mutationFn: (input: QuoteRequestInput) => IntegrationsService.createQuote(input),
  });

export const useCreateShipment = (): UseMutationResult<Shipment, Error, CreateShipmentInput> =>
  useMutation({
    mutationFn: (input: CreateShipmentInput) => IntegrationsService.createShipment(input),
  });

/**
 * The lookup is deliberately a query rather than a mutation: the same
 * identifier searched twice reads the cache, and an empty result is a state of
 * the search that survives a re-render.
 */
export const useShipment = (id: string): UseQueryResult<Shipment> =>
  useQuery({
    queryKey: integrationsKeys.shipment(id),
    queryFn: ({ signal }) => IntegrationsService.getShipment(id, signal),
    enabled: id !== '',
    // "No such shipment" is the final answer; asking again cannot change it.
    retry: (failureCount, error) =>
      !isShipmentMissing(error) && !isModuleUnavailable(error) && failureCount < MAX_ATTEMPTS,
  });
