/**
 * The window a report covers when nothing has been picked.
 *
 * A fixed month, not "the last thirty days". A relative default makes an
 * untouched page depend on the day it is opened: the data in this system sits
 * at known dates, and a window measured backwards from the clock walks off the
 * end of it and draws an empty chart — which reads as a broken screen rather
 * than as an honest answer about a period with nothing in it.
 *
 * The same month is the API's default, so an untouched page and a page that
 * has been reset ask for the same window instead of two that differ by the
 * moment of the request.
 *
 * Calendar days, inclusive at both ends, because that is what a date picker
 * shows. The conversion to the half-open instant range the API reads happens
 * in each section's `toWireRange`.
 */

export const DEFAULT_REPORT_RANGE = {
  from: '2026-01-01',
  to: '2026-01-31',
} as const;

/** Human name of the window above, for text a reader sees. */
export const DEFAULT_REPORT_RANGE_LABEL = 'січень 2026';
