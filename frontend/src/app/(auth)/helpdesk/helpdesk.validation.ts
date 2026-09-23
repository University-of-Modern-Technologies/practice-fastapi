import { z } from 'zod';
import type { TicketChannel, TicketPriority } from '@/shared/constants';

/**
 * Mirrors the rules the API enforces so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */

export const TICKET_SUBJECT_MAX = 200;
export const TICKET_BODY_MAX = 5000;
export const TICKET_NOTE_MAX = 500;

export const ticketSubjectSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть тему звернення')
  .max(TICKET_SUBJECT_MAX, `Не більше ${TICKET_SUBJECT_MAX} символів`);

export const ticketBodySchema = z
  .string()
  .trim()
  .min(1, 'Опишіть звернення')
  .max(TICKET_BODY_MAX, `Не більше ${TICKET_BODY_MAX} символів`);

/**
 * The note that travels with a transition. Empty is allowed — the contract
 * marks it optional — so a blank field must not become an empty string on the
 * wire, and the trimming happens before the length is judged.
 */
export const ticketNoteSchema = z
  .string()
  .trim()
  .max(TICKET_NOTE_MAX, `Коментар — не більше ${TICKET_NOTE_MAX} символів`)
  .optional()
  .or(z.literal(''));

/** What the form holds while it is being filled in. */
export interface TicketFormValues {
  readonly subject: string;
  readonly body: string;
  readonly channel: TicketChannel;
  readonly priority: TicketPriority;
  readonly contactId?: string | undefined;
  readonly assigneeId?: string | undefined;
  readonly ownerId?: string | undefined;
}

/** What the transition dialog holds: the target status is fixed by the button. */
export interface TicketTransitionFormValues {
  readonly note?: string | undefined;
}
