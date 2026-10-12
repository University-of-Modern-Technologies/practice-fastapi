import { DateTime } from '@/lib/date-time';

/**
 * The window a report covers when nothing has been picked.
 *
 * From a fixed start to today, not "the last thirty days". A window measured
 * backwards from the clock walks off the end of the data once enough time has
 * passed and draws an empty chart — which reads as a broken screen rather than
 * as an honest answer about a period with nothing in it. A fixed start keeps
 * the demonstration data in view however late the page is opened; an end at
 * today keeps what was entered this morning in view as well.
 *
 * The API applies the same window when a request names none, but the client
 * always names it: the dates travel in every request, so a cached answer is
 * keyed by the day it was asked for and the next day asks afresh.
 *
 * Calendar days, inclusive at both ends, because that is what a date picker
 * shows. A day is the day in the display zone (Kyiv), the same zone every date
 * on screen is drawn in; `toReportWindow` turns the pair into the half-open
 * instant range the API reads.
 */

export const DEFAULT_REPORT_FROM = '2026-01-01';

/** Human name of the default window, for text a reader sees. */
export const DEFAULT_REPORT_RANGE_LABEL = 'з 1 січня 2026 по сьогодні';

/**
 * Widest window the API scans in one request; anything larger answers 400.
 * Five years, so the default window, which grows by a day every day, stays
 * inside it for years — and `defaultReportRange` keeps it inside afterwards.
 */
export const MAX_REPORT_RANGE_DAYS = 1830;

/**
 * Days the default window may span. One short of the maximum on purpose: the
 * API measures the window in hours, and a span that crosses a clock change
 * gains an hour it would count against the limit.
 */
const DEFAULT_WINDOW_DAYS = MAX_REPORT_RANGE_DAYS - 1;

export interface CalendarWindow {
  readonly from: string;
  readonly to: string;
}

/**
 * The default window as calendar days: from the fixed start to today in Kyiv.
 * Once the fixed start falls further back than the API is willing to scan, the
 * start follows the clock instead, so the default never becomes a 400.
 */
export const defaultReportRange = (now: number = Date.now()): CalendarWindow => {
  const to = DateTime.today(now);
  const earliest = DateTime.addDays(to, -(DEFAULT_WINDOW_DAYS - 1));
  return { from: DEFAULT_REPORT_FROM < earliest ? earliest : DEFAULT_REPORT_FROM, to };
};

/** An instant normalised to UTC; anything unreadable is kept so the caller can name it. */
const toInstant = (value: string): string => {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? value : new Date(parsed).toISOString();
};

/**
 * Calendar days → the half-open `[from, to)` instant range the reports read.
 * The end is pushed to the following midnight, otherwise picking "today" would
 * ask for a window that contains none of today's records. A value that is
 * already an instant passes through untouched.
 */
export const toReportWindow = (range: CalendarWindow): CalendarWindow => ({
  from: DateTime.dayStart(range.from) ?? toInstant(range.from),
  to: DateTime.nextDayStart(range.to) ?? toInstant(range.to),
});
