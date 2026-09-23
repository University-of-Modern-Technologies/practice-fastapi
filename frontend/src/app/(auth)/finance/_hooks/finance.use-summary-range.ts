'use client';

import { useMemo } from 'react';
import { useListParams, type ListParamsPatch } from '@/shared/hooks';
import {
  describeRangeIssue,
  resolveSummaryRange,
  toWireRange,
  type CalendarRange,
  type WireRange,
} from '../finance.validation';

/** Everything the summary keeps in the query string, so a view is a link. */
export const SUMMARY_FILTERS = ['from', 'to'] as const;

export type SummaryFilter = (typeof SUMMARY_FILTERS)[number];

export interface SummaryRangeState {
  /** The window as the picker shows it — calendar days. */
  readonly calendar: CalendarRange;
  /** The same window as the API reads it — ISO instants, end exclusive. */
  readonly wire: WireRange;
  /** Why the window cannot be used, or null when it can. */
  readonly issue: string | null;
  readonly setParams: (patch: ListParamsPatch<SummaryFilter>) => void;
  readonly resetParams: () => void;
}

/**
 * The period the summary is read for. A window the API would reject is never
 * sent: the reason is shown under the picker instead of arriving as a 400.
 *
 * An untouched picker always opens on the shared reporting month. It does not
 * depend on statement-list data, so the summary can load independently.
 */
export const useSummaryRange = (): SummaryRangeState => {
  const { params, setParams, resetParams } = useListParams<SummaryFilter>({
    filters: SUMMARY_FILTERS,
  });

  const { from, to } = params;

  return useMemo(() => {
    const calendar = resolveSummaryRange(from, to);

    return {
      calendar,
      wire: toWireRange(calendar),
      issue: describeRangeIssue(calendar),
      setParams,
      resetParams,
    };
  }, [from, to, setParams, resetParams]);
};
