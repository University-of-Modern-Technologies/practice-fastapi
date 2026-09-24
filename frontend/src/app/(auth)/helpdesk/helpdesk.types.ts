import type { Id, IsoDate, IsoDateTime } from '@/types/domain';

/**
 * A ticket as the API returns it. `number` is the human handle operators quote
 * to each other — it is issued by the server and never edited here, while `id`
 * stays the only thing a request is addressed by.
 */
export interface Ticket {
  readonly id: Id;
  readonly number: string;
  readonly subject: string;
  readonly body: string;
  readonly channel: TicketChannel;
  readonly status: TicketStatus;
  readonly priority: TicketPriority;
  readonly contactId: Id | null;
  readonly assigneeId: Id | null;
  /** Carrier of the `OWN` scope: a viewer sees the tickets where this is them. */
  readonly ownerId: Id;
  readonly openedAt: IsoDateTime;
  /** Set the moment the ticket reaches `RESOLVED`; cleared when it leaves it. */
  readonly resolvedAt: IsoDateTime | null;
  readonly version: number;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/**
 * One step of the ticket's history. The shape is the published one; no endpoint
 * in this contract returns it, so nothing in the client reads it yet.
 */
import type { TicketChannel, TicketPriority, TicketStatus } from '@/shared/constants';

export interface TicketStatusLog {
  readonly id: Id;
  readonly ticketId: Id;
  readonly fromStatus: TicketStatus | null;
  readonly toStatus: TicketStatus;
  readonly changedById: Id;
  readonly changedAt: IsoDateTime;
  readonly note: string | null;
}

/** The only columns the API agrees to order by; anything else answers 400. */
export const TICKET_SORT_FIELDS = [
  'createdAt',
  'updatedAt',
  'openedAt',
  'priority',
  'status',
] as const;

export type TicketSortField = (typeof TICKET_SORT_FIELDS)[number];

export const isTicketSortField = (value: string | undefined): value is TicketSortField =>
  value !== undefined && (TICKET_SORT_FIELDS as readonly string[]).includes(value);

/**
 * Filters this list understands, and the set `useListParams` keeps in the URL.
 * `contactId` has no control of its own: it is how a contact card would link to
 * the tickets raised about that person, and the link has to survive a reload.
 */
export const TICKET_FILTERS = [
  'search',
  'status',
  'channel',
  'priority',
  'contactId',
  'assigneeId',
  'ownerId',
  'openedFrom',
  'openedTo',
] as const;

export type TicketFilter = (typeof TICKET_FILTERS)[number];

export interface TicketListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly status?: TicketStatus;
  readonly channel?: TicketChannel;
  readonly priority?: TicketPriority;
  readonly contactId?: Id;
  readonly assigneeId?: Id;
  readonly ownerId?: Id;
  readonly openedFrom?: IsoDate;
  readonly openedTo?: IsoDate;
  readonly sortBy?: TicketSortField;
  readonly sortOrder?: 'asc' | 'desc';
}

/**
 * A new ticket always starts at `NEW`, so the status is not part of the input,
 * and `number` is issued by the server rather than typed by the operator.
 */
export interface CreateTicketInput {
  readonly subject: string;
  readonly body: string;
  readonly channel: TicketChannel;
  readonly priority?: TicketPriority;
  readonly contactId?: Id;
  readonly assigneeId?: Id;
  readonly ownerId?: Id;
}

/**
 * `status` is deliberately absent: it only ever moves through
 * `POST /helpdesk/tickets/:id/transitions`, where the machine is checked and
 * `resolvedAt` is maintained. A PATCH that carried it would bypass both.
 *
 * `null` is meaningful on the two references — it is how a contact or an
 * assignee is unlinked. `ownerId` cannot be cleared: every ticket has an owner.
 */
export interface UpdateTicketInput {
  readonly version: number;
  readonly subject?: string;
  readonly body?: string;
  readonly channel?: TicketChannel;
  readonly priority?: TicketPriority;
  readonly contactId?: Id | null;
  readonly assigneeId?: Id | null;
  readonly ownerId?: Id;
}

export interface TransitionTicketInput {
  readonly version: number;
  readonly toStatus: TicketStatus;
  readonly note?: string;
}

/** Error codes this module reacts to by name rather than by status alone. */
export const TICKET_ERROR = {
  notFound: 'TICKET_NOT_FOUND',
  duplicateNumber: 'TICKET_DUPLICATE_NUMBER',
  transition: 'TICKET_TRANSITION_NOT_ALLOWED',
  conflict: 'TICKET_CONCURRENT_MODIFICATION',
  contactNotFound: 'TICKET_CONTACT_NOT_FOUND',
  assigneeNotFound: 'TICKET_ASSIGNEE_NOT_FOUND',
} as const;

/**
 * `details` of a refused transition: what the record was, and where it could
 * have gone. Read defensively — the contract names the code and the status of
 * this refusal but not the body that comes with it, so a build that sends
 * nothing must still leave the page with something to say.
 */
export interface TicketTransitionDetails {
  readonly from: string;
  readonly to: string;
  readonly allowed: readonly string[];
}

export const asTransitionDetails = (details: unknown): TicketTransitionDetails | null => {
  if (typeof details !== 'object' || details === null) return null;
  const { from, to, allowed } = details as Partial<TicketTransitionDetails>;
  if (typeof from !== 'string' || typeof to !== 'string' || !Array.isArray(allowed)) return null;
  return {
    from,
    to,
    allowed: allowed.filter((status): status is string => typeof status === 'string'),
  };
};
