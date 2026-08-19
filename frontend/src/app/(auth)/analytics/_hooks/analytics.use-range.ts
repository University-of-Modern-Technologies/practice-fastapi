'use client';

import { useMemo } from 'react';
import { useListParams, type ListParamsPatch } from '@/shared/hooks';
import {
  isAnalyticsPeriod,
  type AnalyticsPeriod,
  type CalendarRange,
  type DateRange,
} from '../analytics.types';
import {
  describeRangeIssue,
  resolveLimit,
  resolveRange,
  resolveThreshold,
  toWireRange,
} from '../analytics.validation';

/** Everything this page keeps in the query string, so a view can be shared as a link. */
export const ANALYTICS_FILTERS = [
  'from',
  'to',
  'period',
  'limit',
  'stockThreshold',
  'stockLimit',
  'warehouseId',
] as const;

export type AnalyticsFilter = (typeof ANALYTICS_FILTERS)[number];

export interface AnalyticsRangeState {
  /** The window as the picker shows it — calendar days. */
  readonly calendar: CalendarRange;
  /** The same window as the API reads it — ISO instants, end exclusive. */
  readonly wire: DateRange;
  /** Why the window cannot be used, or null when it can. */
  readonly issue: string | null;
  readonly period: AnalyticsPeriod;
  readonly limit: number;
  readonly stockThreshold: number;
  readonly stockLimit: number;
  readonly warehouseId: string | undefined;
  readonly setParams: (patch: ListParamsPatch<AnalyticsFilter>) => void;
  readonly resetParams: () => void;
}

/**
 * One period for the whole page. The four range reports read the same window,
 * so a user comparing revenue with the funnel is never looking at two months at
 * once because one card kept its own state.
 */
export const useAnalyticsRange = (): AnalyticsRangeState => {
  const { params, setParams, resetParams } = useListParams<AnalyticsFilter>({
    filters: ANALYTICS_FILTERS,
  });

  const { from, to, period, limit, stockThreshold, stockLimit, warehouseId } = params;

  return useMemo(() => {
    const calendar = resolveRange(from, to);

    return {
      calendar,
      wire: toWireRange(calendar),
      issue: describeRangeIssue(calendar),
      period: isAnalyticsPeriod(period) ? period : 'day',
      limit: resolveLimit(limit),
      stockThreshold: resolveThreshold(stockThreshold),
      stockLimit: resolveLimit(stockLimit),
      warehouseId: warehouseId === '' ? undefined : warehouseId,
      setParams,
      resetParams,
    };
  }, [from, to, period, limit, stockThreshold, stockLimit, warehouseId, setParams, resetParams]);
};
