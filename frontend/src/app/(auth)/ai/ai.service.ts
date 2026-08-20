import { ApiError, http } from '@/shared/api';
import type {
  DealSummary,
  DealSummaryInput,
  InquiryClassification,
  InquiryClassificationInput,
} from './ai.types';

const ROUTES = {
  dealSummary: '/ai/summaries/deal',
  inquiryClassification: '/ai/classify/inquiry',
} as const;

/** Blank optional values are dropped: an empty string is not a valid absence here. */
const present = (value: string | undefined | null): value is string =>
  typeof value === 'string' && value.trim() !== '';

/**
 * Rebuilt field by field rather than spread. The contract lists exactly which
 * parts of a deal may reach a language provider, and rebuilding is what
 * guarantees that a property added to the deal entity later cannot travel with
 * the request just because it happened to be on the object at runtime.
 */
export const toDealSummaryBody = (input: DealSummaryInput): Readonly<Record<string, unknown>> => ({
  id: input.id.trim(),
  title: input.title.trim(),
  stage: input.stage.trim(),
  ...(present(input.amount) ? { amount: input.amount.trim() } : {}),
  ...(present(input.currency) ? { currency: input.currency.trim().toUpperCase() } : {}),
  ...(input.probability === undefined || input.probability === null
    ? {}
    : { probability: input.probability }),
  ...(present(input.expectedCloseDate) ? { expectedCloseDate: input.expectedCloseDate } : {}),
  ...(present(input.notes) ? { notes: input.notes.trim() } : {}),
});

export const toInquiryBody = (
  input: InquiryClassificationInput,
): Readonly<Record<string, unknown>> => ({ text: input.text.trim() });

/**
 * The assistant is not part of every API build the client may be pointed at. A
 * route that is absent answers 404, and a build that does not serve it at all
 * fails at the transport — both mean "this section is not here", which is a
 * different thing from "the request failed" and must not be reported as one.
 *
 * Both routes are POST, so this can only be learned from the first attempt the
 * user makes: there is nothing to probe on load.
 */
export const isModuleUnavailable = (error: unknown): boolean => {
  if (!(error instanceof ApiError)) return false;
  return error.status === 404 || error.code === 'NETWORK_ERROR';
};

export const AiService = {
  summariseDeal: (input: DealSummaryInput, signal?: AbortSignal): Promise<DealSummary> =>
    http.post<DealSummary>(ROUTES.dealSummary, toDealSummaryBody(input), {
      ...(signal ? { signal } : {}),
    }),

  classifyInquiry: (
    input: InquiryClassificationInput,
    signal?: AbortSignal,
  ): Promise<InquiryClassification> =>
    http.post<InquiryClassification>(ROUTES.inquiryClassification, toInquiryBody(input), {
      ...(signal ? { signal } : {}),
    }),
};
