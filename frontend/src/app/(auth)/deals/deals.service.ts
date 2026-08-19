import { http, type Page, type QueryValue } from '@/shared/api';
import { listQuery } from '@/shared/api/query-builder';
import { DEAL_STAGES } from '@/shared/constants';
import type { ListParams } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import {
  isDealSortField,
  type CreateDealInput,
  type Deal,
  type DealFilter,
  type DealListQuery,
  type TransitionDealInput,
  type UpdateDealInput,
} from './deals.types';

const ROUTES = {
  collection: '/deals',
  byId: (id: Id): string => `/deals/${id}`,
  transitions: (id: Id): string => `/deals/${id}/transitions`,
} as const;

/**
 * Turns the query string state into the shape the API expects. Every filter is
 * text in the URL, so a hand-edited link has to be narrowed down here — an
 * unknown stage or a sort column the API does not know would otherwise turn the
 * whole page into a 400.
 */
export const toDealListQuery = (params: ListParams<DealFilter>): DealListQuery =>
  listQuery(params)
    .text('search')
    .text('ownerId')
    .text('contactId')
    .oneOf('stage', DEAL_STAGES)
    .text('minAmount')
    .text('maxAmount')
    .integer('minProbability', { min: 0, max: 100 })
    .integer('maxProbability', { min: 0, max: 100 })
    .text('expectedCloseFrom')
    .text('expectedCloseTo')
    .sort(isDealSortField)
    .build<DealListQuery>();

/**
 * Rebuilt field by field rather than spread: it guarantees `stage` cannot reach
 * a PATCH even if a caller puts it into the object at runtime. `null` is kept
 * where it is meaningful — it is how a contact or a date gets cleared.
 */
const toUpdateBody = (input: UpdateDealInput): Readonly<Record<string, unknown>> => ({
  version: input.version,
  ...(input.ownerId === undefined ? {} : { ownerId: input.ownerId }),
  ...(input.contactId === undefined ? {} : { contactId: input.contactId }),
  ...(input.title === undefined ? {} : { title: input.title }),
  ...(input.amount === undefined ? {} : { amount: input.amount }),
  ...(input.currency === undefined ? {} : { currency: input.currency }),
  ...(input.probability === undefined ? {} : { probability: input.probability }),
  ...(input.expectedCloseDate === undefined ? {} : { expectedCloseDate: input.expectedCloseDate }),
});

export const DealsService = {
  list: (query: DealListQuery, signal?: AbortSignal): Promise<Page<Deal>> =>
    http.get<Page<Deal>>(ROUTES.collection, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  getById: (id: Id, signal?: AbortSignal): Promise<Deal> =>
    http.get<Deal>(ROUTES.byId(id), { ...(signal ? { signal } : {}) }),

  create: (input: CreateDealInput): Promise<Deal> => http.post<Deal>(ROUTES.collection, input),

  update: (id: Id, input: UpdateDealInput): Promise<Deal> =>
    http.patch<Deal>(ROUTES.byId(id), toUpdateBody(input)),

  /** The only way the stage moves; the API checks the machine and the odds here. */
  transition: (id: Id, input: TransitionDealInput): Promise<Deal> =>
    http.post<Deal>(ROUTES.transitions(id), {
      version: input.version,
      stage: input.stage,
      ...(input.probability === undefined ? {} : { probability: input.probability }),
    }),

  /** The version travels in the query string here — a DELETE carries no body. */
  remove: (id: Id, version: number): Promise<void> =>
    http.delete<void>(ROUTES.byId(id), { params: { version } }),
};
