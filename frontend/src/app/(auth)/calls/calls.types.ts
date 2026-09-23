import type { CallDirection, CallDisposition } from '@/shared/constants';
import type { Id, IsoDate, IsoDateTime } from '@/types/domain';

/**
 * A call as the API returns it.
 *
 * Three of its references are nullable at once, and that is the normal state of
 * a fresh record rather than damaged data: a call arrives from the provider
 * before anyone has decided who it was with, what it was about, or whose it is.
 * Every screen in this module is written from that assumption — an unlinked call
 * is a call waiting to be triaged, not a broken row.
 */
export interface Call {
  readonly id: Id;
  /** The provider's own identifier; it is what makes a repeated sync idempotent. */
  readonly externalId: string;
  readonly direction: CallDirection;
  readonly disposition: CallDisposition;
  readonly fromNumber: string;
  readonly toNumber: string;
  readonly startedAt: IsoDateTime;
  readonly durationSeconds: number;
  readonly contactId: Id | null;
  readonly dealId: Id | null;
  /** Carrier of the `OWN` scope — and empty on a call nobody has claimed. */
  readonly ownerId: Id | null;
  readonly recordingUrl: string | null;
  readonly notes: string | null;
  readonly version: number;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/** The only columns the API agrees to order by; anything else answers 400. */
export const CALL_SORT_FIELDS = ['startedAt', 'createdAt', 'durationSeconds'] as const;

export type CallSortField = (typeof CALL_SORT_FIELDS)[number];

export const isCallSortField = (value: string | undefined): value is CallSortField =>
  value !== undefined && (CALL_SORT_FIELDS as readonly string[]).includes(value);

/**
 * Filters this list understands, and the set `useListParams` keeps in the URL.
 * `contactId` and `dealId` have no controls of their own: they are how a contact
 * or a deal card links to the calls about it, and the link has to survive a
 * reload.
 */
export const CALL_FILTERS = [
  'search',
  'direction',
  'disposition',
  'contactId',
  'dealId',
  'ownerId',
  'startedFrom',
  'startedTo',
  'hasContact',
] as const;

export type CallFilter = (typeof CALL_FILTERS)[number];

export interface CallListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly direction?: CallDirection;
  readonly disposition?: CallDisposition;
  readonly contactId?: Id;
  readonly dealId?: Id;
  readonly ownerId?: Id;
  readonly startedFrom?: IsoDate;
  readonly startedTo?: IsoDate;
  /** Narrows to the calls that have been attributed to someone, or to those that have not. */
  readonly hasContact?: boolean;
  readonly sortBy?: CallSortField;
  readonly sortOrder?: 'asc' | 'desc';
}

/**
 * There is no create input, and no create route: a call enters the journal only
 * through `POST /calls/sync`. The operator records who it was with, not that it
 * happened.
 *
 * `null` is meaningful on all three references — it is how a call is detached
 * from a contact, a deal or an owner. Unlike a ticket, a call may end up owned
 * by nobody, which is the state it arrived in.
 */
export interface UpdateCallInput {
  readonly version: number;
  readonly contactId?: Id | null;
  readonly dealId?: Id | null;
  readonly ownerId?: Id | null;
  readonly notes?: string | null;
}

/**
 * Attaching a call to a contact or a deal is its own action rather than a field
 * on the form: it is the decision the journal exists for, it is audited under
 * `call.linked`, and a PATCH would bury it among the notes.
 *
 * It only ever attaches. `null` is refused here and at least one of the two
 * references must be present — detaching is a PATCH, and the interface has to
 * keep the two apart rather than offer one control that silently does both.
 */
export interface LinkCallInput {
  readonly version: number;
  readonly contactId?: Id;
  readonly dealId?: Id;
}

/**
 * What one round of pulling from the provider did. A call the journal already
 * knows is `skipped` — an ordinary outcome and not a failure, which is why the
 * repeat of a sync has no error of its own to report.
 */
export interface CallSyncResult {
  readonly fetched: number;
  readonly created: number;
  /** Already known by `externalId` — a repeated sync creates no duplicates. */
  readonly skipped: number;
}

/**
 * A short-lived address for the recording. It expires, so it is never stored
 * with the record and never reused after `expiresAt` — the page asks again.
 */
export interface CallRecording {
  readonly url: string;
  readonly expiresAt: IsoDateTime;
}

/** Error codes this module reacts to by name rather than by status alone. */
export const CALL_ERROR = {
  notFound: 'CALL_NOT_FOUND',
  conflict: 'CALL_CONCURRENT_MODIFICATION',
  contactNotFound: 'CALL_CONTACT_NOT_FOUND',
  dealNotFound: 'CALL_DEAL_NOT_FOUND',
  recordingUnavailable: 'CALL_RECORDING_UNAVAILABLE',
  providerUnavailable: 'CALL_PROVIDER_UNAVAILABLE',
} as const;

/**
 * Wording for the failures of the provider-facing action. A telephony provider
 * that is down is not a broken section: the journal keeps reading, and the
 * operator needs to be told which of the two happened.
 */
export const CALL_SYNC_MESSAGES: Readonly<Record<string, string>> = {
  [CALL_ERROR.providerUnavailable]:
    'Провайдер телефонії недоступний — журнал показано без нових дзвінків',
};
