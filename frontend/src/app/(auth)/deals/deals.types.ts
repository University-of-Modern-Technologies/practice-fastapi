import type { DealStage } from '@/shared/constants';
import type { CurrencyCode, Id, IsoDate, IsoDateTime, MoneyWire } from '@/types/domain';

/**
 * A deal as the API returns it. `amount` is a fixed-scale string and
 * `expectedCloseDate` a calendar date — neither carries a zone or a float.
 */
export interface Deal {
  readonly id: Id;
  readonly ownerId: Id;
  readonly contactId: Id | null;
  readonly title: string;
  readonly stage: DealStage;
  readonly amount: MoneyWire;
  readonly currency: CurrencyCode;
  readonly probability: number;
  readonly version: number;
  readonly expectedCloseDate: IsoDate | null;
  /** Set the moment the deal reaches a terminal stage; null until then. */
  readonly closedAt: IsoDateTime | null;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/** The only columns the API agrees to order by; anything else answers 400. */
export const DEAL_SORT_FIELDS = [
  'createdAt',
  'updatedAt',
  'title',
  'amount',
  'probability',
  'expectedCloseDate',
] as const;

export type DealSortField = (typeof DEAL_SORT_FIELDS)[number];

export const isDealSortField = (value: string | undefined): value is DealSortField =>
  value !== undefined && (DEAL_SORT_FIELDS as readonly string[]).includes(value);

/**
 * Filters this list understands, and the set `useListParams` keeps in the URL.
 * `contactId` has no control of its own: it is how a contact card links to the
 * deals it owns, and the link has to survive a reload.
 */
export const DEAL_FILTERS = [
  'search',
  'ownerId',
  'contactId',
  'stage',
  'minAmount',
  'maxAmount',
  'minProbability',
  'maxProbability',
  'expectedCloseFrom',
  'expectedCloseTo',
] as const;

export type DealFilter = (typeof DEAL_FILTERS)[number];

export interface DealListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly ownerId?: Id;
  readonly contactId?: Id;
  readonly stage?: DealStage;
  readonly minAmount?: MoneyWire;
  readonly maxAmount?: MoneyWire;
  readonly minProbability?: number;
  readonly maxProbability?: number;
  readonly expectedCloseFrom?: IsoDate;
  readonly expectedCloseTo?: IsoDate;
  readonly sortBy?: DealSortField;
  readonly sortOrder?: 'asc' | 'desc';
}

/** A new deal always starts at `LEAD`, so the stage is not part of the input. */
export interface CreateDealInput {
  readonly ownerId?: Id;
  readonly contactId?: Id;
  readonly title: string;
  readonly amount: MoneyWire;
  readonly currency?: CurrencyCode;
  readonly probability?: number;
  readonly expectedCloseDate?: IsoDate;
}

/**
 * `stage` is deliberately absent: the stage only ever moves through
 * `POST /deals/:id/transitions`, where the state machine and the probability
 * rules are checked together. A PATCH that carried it would bypass both.
 */
export interface UpdateDealInput {
  readonly version: number;
  readonly ownerId?: Id;
  readonly contactId?: Id | null;
  readonly title?: string;
  readonly amount?: MoneyWire;
  readonly currency?: CurrencyCode;
  readonly probability?: number;
  readonly expectedCloseDate?: IsoDate | null;
}

export interface TransitionDealInput {
  readonly version: number;
  readonly stage: DealStage;
  readonly probability?: number;
}

/** Error codes this module reacts to by name rather than by status alone. */
export const DEAL_ERROR = {
  conflict: 'DEAL_CONCURRENT_MODIFICATION',
  transition: 'INVALID_DEAL_STAGE_TRANSITION',
  probability: 'INVALID_DEAL_PROBABILITY',
} as const;

/** `details` of a refused transition: what the record was, and where it may go. */
export interface DealTransitionDetails {
  readonly from: string;
  readonly to: string;
  readonly allowed: readonly string[];
}

/**
 * A 409 and a refused transition share a status code, so the branch is taken on
 * the shape of `details` rather than on the status alone.
 */
export const asTransitionDetails = (details: unknown): DealTransitionDetails | null => {
  if (typeof details !== 'object' || details === null) return null;
  const { from, to, allowed } = details as Partial<DealTransitionDetails>;
  if (typeof from !== 'string' || typeof to !== 'string' || !Array.isArray(allowed)) return null;
  return {
    from,
    to,
    allowed: allowed.filter((stage): stage is string => typeof stage === 'string'),
  };
};
