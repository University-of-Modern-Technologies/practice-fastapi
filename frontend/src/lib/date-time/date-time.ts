import dayjs, { type Dayjs } from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(relativeTime);

/**
 * Everything is rendered in one fixed zone rather than the viewer's own. The
 * page is server-rendered first and hydrated in the browser; if the two sides
 * resolved the same instant to different clock times, React would report a
 * mismatch on every timestamp in every table.
 */
export const DISPLAY_TIME_ZONE = 'Europe/Kyiv';

/** Shown where a value is absent, so a column never reads "Invalid Date". */
export const EMPTY_VALUE = '—';

const DATE_FORMAT = 'DD.MM.YYYY';
const TIME_FORMAT = 'HH:mm';
const DATE_TIME_FORMAT = 'DD.MM.YYYY HH:mm';

/** Calendar dates travel without a zone and must not be shifted by one. */
const WIRE_DATE_FORMAT = 'YYYY-MM-DD';
const WIRE_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const parse = (value: string): Dayjs | null => {
  // A bare calendar date is a wall-clock day, not an instant: reading it in a
  // zone would move "2026-08-12" to the 11th for anyone west of the meridian.
  const parsed = WIRE_DATE_PATTERN.test(value)
    ? dayjs(value, WIRE_DATE_FORMAT)
    : dayjs(value).tz(DISPLAY_TIME_ZONE);
  return parsed.isValid() ? parsed : null;
};

export class DateTime {
  /** `"2026-08-12T15:23:45.123Z"` or `"2026-08-12"` → `"12.08.2026"`. */
  static toDate(value: string | null | undefined): string {
    if (!value) return EMPTY_VALUE;
    return parse(value)?.format(DATE_FORMAT) ?? EMPTY_VALUE;
  }

  /** → `"12.08.2026 15:23"`. */
  static toDateTime(value: string | null | undefined): string {
    if (!value) return EMPTY_VALUE;
    return parse(value)?.format(DATE_TIME_FORMAT) ?? EMPTY_VALUE;
  }

  /** → `"15:23"`. */
  static toTime(value: string | null | undefined): string {
    if (!value) return EMPTY_VALUE;
    return parse(value)?.format(TIME_FORMAT) ?? EMPTY_VALUE;
  }

  /** → `"3 години тому"`. Only for feeds, never for a value the user edits. */
  static toRelative(value: string | null | undefined): string {
    if (!value) return EMPTY_VALUE;
    return parse(value)?.fromNow() ?? EMPTY_VALUE;
  }

  /** → `"12.08.2026 — 15.08.2026"`, collapsing an open or single-day range. */
  static range(from: string | null | undefined, to: string | null | undefined): string {
    const start = from ? DateTime.toDate(from) : null;
    const end = to ? DateTime.toDate(to) : null;
    if (start && end) return start === end ? start : `${start} — ${end}`;
    if (start) return `від ${start}`;
    if (end) return `до ${end}`;
    return EMPTY_VALUE;
  }

  /** A picker value → the calendar date the API expects, or nothing to omit it. */
  static toWireDate(value: Dayjs | null | undefined): string | undefined {
    return value?.isValid() ? value.format(WIRE_DATE_FORMAT) : undefined;
  }

  /** A picker value → an instant in UTC, the only form the API accepts. */
  static toWireDateTime(value: Dayjs | null | undefined): string | undefined {
    return value?.isValid() ? value.utc().toISOString() : undefined;
  }

  /** Wire value → a picker value; invalid input yields an empty field. */
  static toPicker(value: string | null | undefined): Dayjs | null {
    if (!value) return null;
    return parse(value);
  }

  /** Today as a calendar date, for filter defaults. */
  static today(): string {
    return dayjs().tz(DISPLAY_TIME_ZONE).format(WIRE_DATE_FORMAT);
  }

  // `daysAgo` used to live here, and it is deliberately gone. It had one
  // purpose — the default reporting window, measured backwards from the clock
  // — and that default is now a fixed month, because a window that slides
  // walks off the end of the data and draws an empty screen for a full
  // system. A helper kept for a caller that no longer exists is how the thing
  // it was removed for comes back.
}
