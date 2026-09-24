import { z } from 'zod';

/**
 * Mirrors the rules the API enforces so an obviously wrong form never becomes a
 * request. The server validates independently — this only saves a round trip.
 */

export const CALL_NOTES_MAX = 2000;

/**
 * The note is optional, and an emptied field means "there is nothing to say"
 * rather than "leave what was there": it travels as `null`, which is how the
 * PATCH clears it. The trimming happens before the length is judged.
 */
export const callNotesSchema = z
  .string()
  .trim()
  .max(CALL_NOTES_MAX, `Не більше ${CALL_NOTES_MAX} символів`)
  .optional()
  .or(z.literal(''));

/** What the edit form holds while it is being filled in. */
export interface CallFormValues {
  readonly notes?: string | undefined;
  readonly ownerId?: string | undefined;
}

/**
 * What the link dialog holds. Both fields are optional on the wire, but a
 * dialog that sends neither would be an action with no content, so the page
 * keeps the submit button shut until one of them is picked.
 */
export interface CallLinkFormValues {
  readonly contactId?: string | undefined;
  readonly dealId?: string | undefined;
}
