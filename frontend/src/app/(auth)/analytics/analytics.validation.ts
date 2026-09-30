import { MAX_REPORT_RANGE_DAYS, defaultReportRange } from '@/shared/constants';
import type { CalendarRange, DateRange } from './analytics.types';

const DAY_MS = 86_400_000;

/** Widest window the API scans in one request; anything larger answers 400. */
export const MAX_RANGE_DAYS = MAX_REPORT_RANGE_DAYS;

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 100;
export const LIMIT_CHOICES = [5, 10, 20, 50] as const;

export const DEFAULT_STOCK_THRESHOLD = 5;
export const MAX_STOCK_THRESHOLD = 1_000_000;

/** A calendar day as the picker writes it into the query string. */
const CALENDAR_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const isReadableInstant = (value: string): boolean => !Number.isNaN(Date.parse(value));

const readDate = (value: string | undefined): string | undefined =>
  value !== undefined && value !== '' && isReadableInstant(value) ? value : undefined;

/**
 * Fills in what the user has not picked: from the fixed start to today, the
 * window the API applies too. See `shared/constants/reporting`.
 */
export const resolveRange = (from: string | undefined, to: string | undefined): CalendarRange => {
  const fallback = defaultReportRange();
  return { from: readDate(from) ?? fallback.from, to: readDate(to) ?? fallback.to };
};

/**
 * A calendar day names a whole day, not its first millisecond. The interval is
 * half-open, so the end is pushed to the following midnight — otherwise picking
 * "today" would ask for a window that contains none of today's orders.
 */
export const toWireRange = (range: CalendarRange): DateRange => {
  const start = CALENDAR_PATTERN.test(range.from)
    ? Date.parse(`${range.from}T00:00:00.000Z`)
    : Date.parse(range.from);
  const end = CALENDAR_PATTERN.test(range.to)
    ? Date.parse(`${range.to}T00:00:00.000Z`) + DAY_MS
    : Date.parse(range.to);

  return { from: new Date(start).toISOString(), to: new Date(end).toISOString() };
};

/**
 * Says what is wrong with the chosen window, or nothing when it is usable.
 * Checked here so the user reads a hint under the filter instead of a 400 that
 * arrives once per report.
 */
export const describeRangeIssue = (range: CalendarRange): string | null => {
  const wire = toWireRange(range);
  const from = Date.parse(wire.from);
  const to = Date.parse(wire.to);

  if (Number.isNaN(from) || Number.isNaN(to)) return 'Вкажіть коректні дати періоду';
  if (from >= to) return 'Дата «від» має бути раніша за дату «до»';
  if (to - from > MAX_RANGE_DAYS * DAY_MS) {
    return `Період не може перевищувати ${MAX_RANGE_DAYS} днів`;
  }
  return null;
};

const clampInteger = (
  value: string | number | undefined,
  fallback: number,
  min: number,
  max: number,
): number => {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isInteger(parsed) || parsed < min) return fallback;
  return Math.min(parsed, max);
};

/** A hand-edited `limit` narrows nothing rather than turning the page into a 400. */
export const resolveLimit = (value: string | number | undefined): number =>
  clampInteger(value, DEFAULT_LIMIT, 1, MAX_LIMIT);

export const resolveThreshold = (value: string | number | undefined): number =>
  clampInteger(value, DEFAULT_STOCK_THRESHOLD, 0, MAX_STOCK_THRESHOLD);
