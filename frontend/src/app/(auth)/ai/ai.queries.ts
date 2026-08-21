'use client';

import { useMutation, type UseMutationResult } from '@tanstack/react-query';
import { AiService } from './ai.service';
import type {
  DealSummary,
  DealSummaryInput,
  InquiryClassification,
  InquiryClassificationInput,
} from './ai.types';

/**
 * Both calls are writes as far as the client is concerned: they are POSTs the
 * user starts on purpose, they are slow, and nothing on the page should fire
 * one on its own. A mutation is therefore the right shape — never a query with
 * a key that would replay the request on a refocus and pay for it twice.
 *
 * Retries are off: a run that failed already cost the wait, and the server
 * caches successful answers, so a repeat is neither cheap nor more likely to
 * succeed. An absent module in particular must be reported at once.
 */
export const useSummariseDeal = (): UseMutationResult<DealSummary, Error, DealSummaryInput> =>
  useMutation({
    mutationFn: (input: DealSummaryInput) => AiService.summariseDeal(input),
    retry: false,
  });

export const useClassifyInquiry = (): UseMutationResult<
  InquiryClassification,
  Error,
  InquiryClassificationInput
> =>
  useMutation({
    mutationFn: (input: InquiryClassificationInput) => AiService.classifyInquiry(input),
    retry: false,
  });
