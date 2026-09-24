import { ApiError, http, listQuery, type Page, type QueryValue } from '@/shared/api';
import type { ListParams } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import {
  isTicketSortField,
  TICKET_ERROR,
  type CreateTicketInput,
  type Ticket,
  type TicketFilter,
  type TicketListQuery,
  type TransitionTicketInput,
  type UpdateTicketInput,
} from './helpdesk.types';
import { TICKET_CHANNELS, TICKET_PRIORITIES, TICKET_STATUSES } from '@/shared/constants';

const ROUTES = {
  collection: '/helpdesk/tickets',
  byId: (id: Id): string => `/helpdesk/tickets/${id}`,
  transitions: (id: Id): string => `/helpdesk/tickets/${id}/transitions`,
} as const;

/**
 * Turns the query string state into the shape the API expects. Every filter is
 * text in the URL, so a hand-edited link has to be narrowed down here — an
 * unknown status or a sort column the API does not know would otherwise turn
 * the whole page into a 400.
 */
export const toTicketListQuery = (params: ListParams<TicketFilter>): TicketListQuery =>
  listQuery(params)
    .text('search')
    .oneOf('status', TICKET_STATUSES)
    .oneOf('channel', TICKET_CHANNELS)
    .oneOf('priority', TICKET_PRIORITIES)
    .text('contactId')
    .text('assigneeId')
    .text('ownerId')
    .text('openedFrom')
    .text('openedTo')
    .sort(isTicketSortField)
    .build<TicketListQuery>();

/**
 * Not every API build serves the helpdesk, and the client is never told which
 * one it is talking to: a build without the module answers 404 on the very
 * first read of the collection. That is "this section is not here", not "the
 * list failed", and it must not be reported as a failure.
 *
 * Unlike the reporting section, a dead transport is *not* counted here. The
 * helpdesk is an ordinary record-keeping section, and telling an operator that
 * the module is absent when the server is merely unreachable would send them to
 * an administrator for the wrong thing; a lost connection is already worded as
 * itself by the shared error reporter.
 */
export const isModuleUnavailable = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404 && error.code !== TICKET_ERROR.notFound;

/**
 * Rebuilt field by field rather than spread: it guarantees `status` cannot
 * reach a PATCH even if a caller puts it into the object at runtime. `null` is
 * kept where it is meaningful — it is how a contact or an assignee is unlinked.
 */
const toUpdateBody = (input: UpdateTicketInput): Readonly<Record<string, unknown>> => ({
  version: input.version,
  ...(input.subject === undefined ? {} : { subject: input.subject }),
  ...(input.body === undefined ? {} : { body: input.body }),
  ...(input.channel === undefined ? {} : { channel: input.channel }),
  ...(input.priority === undefined ? {} : { priority: input.priority }),
  ...(input.contactId === undefined ? {} : { contactId: input.contactId }),
  ...(input.assigneeId === undefined ? {} : { assigneeId: input.assigneeId }),
  ...(input.ownerId === undefined ? {} : { ownerId: input.ownerId }),
});

/**
 * The only place that knows the shape of the helpdesk endpoints. It holds no
 * React, so its request paths and bodies can be asserted without a DOM.
 */
export const HelpdeskService = {
  list: (query: TicketListQuery, signal?: AbortSignal): Promise<Page<Ticket>> =>
    http.get<Page<Ticket>>(ROUTES.collection, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  getById: (id: Id, signal?: AbortSignal): Promise<Ticket> =>
    http.get<Ticket>(ROUTES.byId(id), { ...(signal ? { signal } : {}) }),

  create: (input: CreateTicketInput): Promise<Ticket> =>
    http.post<Ticket>(ROUTES.collection, input),

  update: (id: Id, input: UpdateTicketInput): Promise<Ticket> =>
    http.patch<Ticket>(ROUTES.byId(id), toUpdateBody(input)),

  /** The only way the status moves; the API checks the machine here. */
  transition: (id: Id, input: TransitionTicketInput): Promise<Ticket> =>
    http.post<Ticket>(ROUTES.transitions(id), {
      version: input.version,
      toStatus: input.toStatus,
      ...(input.note === undefined || input.note === '' ? {} : { note: input.note }),
    }),

  /** The version travels in the query string here — a DELETE carries no body. */
  remove: (id: Id, version: number): Promise<void> =>
    http.delete<void>(ROUTES.byId(id), { params: { version } }),
};
