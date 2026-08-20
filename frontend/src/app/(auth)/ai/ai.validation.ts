import { z } from 'zod';

/**
 * Mirrors the bounds the API enforces on the assistant routes, so an obviously
 * oversized request is stopped before a single token is paid for. The server
 * validates independently — this only saves a round trip.
 */

/** The longest free text either route accepts, as the contract states it. */
export const AI_MAX_INPUT_CHARS = 4_000;

export const AI_MAX_TITLE_CHARS = 200;
export const AI_MAX_STAGE_CHARS = 40;

const UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export const dealIdSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть угоду')
  .regex(UUID_PATTERN, 'Ідентифікатор угоди — UUID');

export const dealTitleSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть назву угоди')
  .max(AI_MAX_TITLE_CHARS, `Не більше ${AI_MAX_TITLE_CHARS} символів`);

export const dealStageSchema = z
  .string()
  .trim()
  .min(1, 'Вкажіть етап угоди')
  .max(AI_MAX_STAGE_CHARS, `Не більше ${AI_MAX_STAGE_CHARS} символів`);

/** Optional on the wire, so an empty field is a valid absence, not an error. */
export const dealNotesSchema = z
  .string()
  .trim()
  .max(AI_MAX_INPUT_CHARS, `Не більше ${AI_MAX_INPUT_CHARS} символів`)
  .optional()
  .or(z.literal(''));

export const inquiryTextSchema = z
  .string()
  .trim()
  .min(1, 'Введіть текст звернення')
  .max(AI_MAX_INPUT_CHARS, `Не більше ${AI_MAX_INPUT_CHARS} символів`);

export interface DealSummaryFormValues {
  dealId: string;
  title: string;
  stage: string;
  notes?: string;
}

export interface InquiryFormValues {
  text: string;
}
