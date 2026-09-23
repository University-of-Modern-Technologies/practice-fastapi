import { ApiError, http, listQuery, type Page, type QueryValue } from '@/shared/api';
import type { ListParams } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import {
  CALL_ERROR,
  isCallSortField,
  type Call,
  type CallFilter,
  type CallListQuery,
  type CallRecording,
  type CallSyncResult,
  type LinkCallInput,
  type UpdateCallInput,
} from './calls.types';
import { CALL_DIRECTIONS, CALL_DISPOSITIONS } from '@/shared/constants';

const ROUTES = {
  collection: '/calls',
  sync: '/calls/sync',
  byId: (id: Id): string => `/calls/${id}`,
  link: (id: Id): string => `/calls/${id}/link`,
  recording: (id: Id): string => `/calls/${id}/recording`,
} as const;

/**
 * Turns the query string state into the shape the API expects. Every filter is
 * text in the URL, so a hand-edited link has to be narrowed down here — an
 * unknown disposition or a sort column the API does not know would otherwise
 * turn the whole page into a 400.
 */
export const toCallListQuery = (params: ListParams<CallFilter>): CallListQuery =>
  listQuery(params)
    .text('search')
    .oneOf('direction', CALL_DIRECTIONS)
    .oneOf('disposition', CALL_DISPOSITIONS)
    .text('contactId')
    .text('dealId')
    .text('ownerId')
    .text('startedFrom')
    .text('startedTo')
    .boolean('hasContact')
    .sort(isCallSortField)
    .build<CallListQuery>();

/**
 * Not every API build serves the call journal, and the client is never told
 * which one it is talking to: a build without the module answers 404 on the
 * very first read of the collection. That is "this section is not here", not
 * "the list failed", and it must not be reported as a failure.
 *
 * A dead transport is deliberately not counted: telling an operator that the
 * module is absent when the server is merely unreachable would send them to an
 * administrator for the wrong thing.
 */
export const isModuleUnavailable = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404 && error.code !== CALL_ERROR.notFound;

/**
 * The provider sits behind the sync action only. Its being down says nothing
 * about the journal — the rows already pulled keep reading — so the page that
 * shows this names the provider rather than blanking the list.
 */
export const isProviderUnavailable = (error: unknown): boolean =>
  error instanceof ApiError && error.code === CALL_ERROR.providerUnavailable;

/** Distinguishes "this call has no recording" from "no such call". */
export const isRecordingUnavailable = (error: unknown): boolean =>
  error instanceof ApiError && error.code === CALL_ERROR.recordingUnavailable;

/**
 * Rebuilt field by field rather than spread: the contract lets a PATCH carry
 * exactly four fields, and rebuilding here guarantees nothing else reaches the
 * request even if a caller puts it into the object at runtime. `null` is kept
 * where it is meaningful — it is how a reference or the note is cleared.
 */
const toUpdateBody = (input: UpdateCallInput): Readonly<Record<string, unknown>> => ({
  version: input.version,
  ...(input.contactId === undefined ? {} : { contactId: input.contactId }),
  ...(input.dealId === undefined ? {} : { dealId: input.dealId }),
  ...(input.ownerId === undefined ? {} : { ownerId: input.ownerId }),
  ...(input.notes === undefined ? {} : { notes: input.notes }),
});

/**
 * The only place that knows the shape of the call endpoints. It holds no React,
 * so its request paths and bodies can be asserted without a DOM.
 */
export const CallsService = {
  list: (query: CallListQuery, signal?: AbortSignal): Promise<Page<Call>> =>
    http.get<Page<Call>>(ROUTES.collection, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  getById: (id: Id, signal?: AbortSignal): Promise<Call> =>
    http.get<Call>(ROUTES.byId(id), { ...(signal ? { signal } : {}) }),

  /**
   * Pulls a batch from the provider. The contract describes no request body, so
   * none is sent; repeating the call creates no duplicates, because the
   * provider's `externalId` is the idempotency key on the server side.
   */
  sync: (): Promise<CallSyncResult> => http.post<CallSyncResult>(ROUTES.sync),

  update: (id: Id, input: UpdateCallInput): Promise<Call> =>
    http.patch<Call>(ROUTES.byId(id), toUpdateBody(input)),

  /**
   * Attaching the call to what it was about. A reference that was not picked is
   * left out rather than sent empty: this action only ever adds a link — `null`
   * is refused — and detaching goes through the PATCH with an explicit `null`.
   */
  link: (id: Id, input: LinkCallInput): Promise<Call> =>
    http.post<Call>(ROUTES.link(id), {
      version: input.version,
      ...(input.contactId === undefined ? {} : { contactId: input.contactId }),
      ...(input.dealId === undefined ? {} : { dealId: input.dealId }),
    }),

  /**
   * A short-lived address for the recording, asked for at the moment it is
   * wanted. It is never cached with the record: the answer carries `expiresAt`,
   * and a link kept past that is a button that fails when it is pressed.
   */
  recording: (id: Id): Promise<CallRecording> => http.get<CallRecording>(ROUTES.recording(id)),

  /** The version travels in the query string here — a DELETE carries no body. */
  remove: (id: Id, version: number): Promise<void> =>
    http.delete<void>(ROUTES.byId(id), { params: { version } }),
};
