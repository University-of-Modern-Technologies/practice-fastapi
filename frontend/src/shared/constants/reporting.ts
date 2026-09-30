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
 * shows. The conversion to the half-open instant range the API reads happens
 * in each section's `toWireRange`. Days are read in UTC, as the API reads them.
 */

export const DEFAULT_REPORT_FROM = '2026-01-01';

/** Human name of the default window, for text a reader sees. */
export const DEFAULT_REPORT_RANGE_LABEL = 'з 1 січня 2026 по сьогодні';

/**
 * Widest window the API scans in one request; anything larger answers 400.
 * Five years, so the default window, which grows by a day every day, stays
 * inside it.
 */
export const MAX_REPORT_RANGE_DAYS = 1830;

/** The default window as calendar days, from the fixed start to today (UTC). */
export const defaultReportRange = (now: number = Date.now()): { from: string; to: string } => ({
  from: DEFAULT_REPORT_FROM,
  to: new Date(now).toISOString().slice(0, 10),
});
