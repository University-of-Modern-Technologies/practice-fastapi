import type { InquiryCategory } from '@/shared/constants';
import type { CurrencyCode, Id, IsoDate, MoneyWire } from '@/types/domain';

/**
 * The exact, explicitly listed fields of a deal the assistant route accepts.
 * Nothing is spread from a deal record: an allow-list is the only reliable way
 * to guarantee that a field added to the entity later — an internal note, an
 * identifier, a value carrying personal data — does not silently start leaving
 * the client with every summary request.
 */
export interface DealSummaryInput {
  readonly id: Id;
  readonly title: string;
  readonly stage: string;
  readonly amount?: MoneyWire | undefined;
  readonly currency?: CurrencyCode | undefined;
  readonly probability?: number | undefined;
  readonly expectedCloseDate?: IsoDate | undefined;
  readonly notes?: string | undefined;
}

export interface DealSummary {
  readonly dealId: Id;
  readonly summary: string;
  /** Which engine answered — diagnostic detail, not a heading. */
  readonly provider: string;
  /** True when the answer came from the server cache instead of the provider. */
  readonly cached: boolean;
}

export interface InquiryClassificationInput {
  readonly text: string;
}

export interface InquiryClassification {
  /**
   * Always one of the labels the dictionary knows. `unknown` is a normal
   * answer, not a failure: the server downgrades to it when the model replied
   * with something outside its closed list.
   */
  readonly category: InquiryCategory;
  /** Share in `[0, 1]`, shown through `formatRate` — never a percentage here. */
  readonly confidence: number;
  readonly provider: string;
  readonly cached: boolean;
}

/** The label that means "the model did not answer from the closed list". */
export const UNKNOWN_CATEGORY = 'unknown';
