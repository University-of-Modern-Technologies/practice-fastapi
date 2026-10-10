import dayjs from 'dayjs';
import { describe, expect, it } from 'vitest';
import { DateTime, EMPTY_VALUE } from './date-time';

describe('DateTime', () => {
  it('formats an instant in the fixed display zone', () => {
    // 15:23 UTC is 18:23 in Kyiv in August — the offset must be applied.
    expect(DateTime.toDateTime('2026-08-12T15:23:45.123Z')).toBe('12.08.2026 18:23');
    expect(DateTime.toDate('2026-08-12T15:23:45.123Z')).toBe('12.08.2026');
    expect(DateTime.toTime('2026-08-12T15:23:45.123Z')).toBe('18:23');
  });

  it('keeps a calendar date on its own day', () => {
    // Reading a bare date as an instant would shift it across the zone boundary.
    expect(DateTime.toDate('2026-08-12')).toBe('12.08.2026');
    expect(DateTime.toDate('2026-01-01')).toBe('01.01.2026');
  });

  it('shows a placeholder instead of an invalid date', () => {
    for (const value of [null, undefined, '', 'not a date']) {
      expect(DateTime.toDate(value)).toBe(EMPTY_VALUE);
      expect(DateTime.toDateTime(value)).toBe(EMPTY_VALUE);
    }
  });

  it('collapses a range to a single day and describes open ends', () => {
    expect(DateTime.range('2026-08-12', '2026-08-15')).toBe('12.08.2026 — 15.08.2026');
    expect(DateTime.range('2026-08-12', '2026-08-12')).toBe('12.08.2026');
    expect(DateTime.range('2026-08-12', null)).toBe('від 12.08.2026');
    expect(DateTime.range(null, '2026-08-15')).toBe('до 15.08.2026');
    expect(DateTime.range(null, null)).toBe(EMPTY_VALUE);
  });

  it('serialises a picker value back to the wire shapes', () => {
    const value = dayjs('2026-08-12T15:23:45.000Z');
    expect(DateTime.toWireDate(value)).toBe('2026-08-12');
    expect(DateTime.toWireDateTime(value)).toBe('2026-08-12T15:23:45.000Z');
  });

  it('omits an absent picker value so the filter drops out of the query', () => {
    expect(DateTime.toWireDate(null)).toBeUndefined();
    expect(DateTime.toWireDateTime(undefined)).toBeUndefined();
  });

  it('tells a bare calendar date from an instant', () => {
    expect(DateTime.isCalendarDate('2026-09-01')).toBe(true);
    expect(DateTime.isCalendarDate('2026-09-01T00:00:00.000Z')).toBe(false);
    expect(DateTime.isCalendarDate(null)).toBe(false);
    expect(DateTime.isCalendarDate('')).toBe(false);
  });

  // The picker shows the stored day and sends the same day back, so an
  // untouched field never moves by one across the zone boundary.
  it('keeps the first and the last day of a month through the picker', () => {
    for (const day of ['2026-09-01', '2026-03-31', '2026-10-25']) {
      expect(DateTime.toWireDate(DateTime.toPicker(day))).toBe(day);
    }
  });

  it('turns a wire value back into a picker value and back again', () => {
    const picker = DateTime.toPicker('2026-08-12');
    expect(picker).not.toBeNull();
    expect(DateTime.toWireDate(picker)).toBe('2026-08-12');
    expect(DateTime.toPicker(null)).toBeNull();
  });

  it('produces a calendar date for filter defaults', () => {
    expect(DateTime.today()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  // 22:30 UTC on the 9th is already 01:30 on the 10th in Kyiv.
  it('reads "today" in Kyiv, not in UTC', () => {
    expect(DateTime.today(Date.parse('2026-10-09T22:30:00.000Z'))).toBe('2026-10-10');
    expect(DateTime.today(Date.parse('2026-10-09T20:59:00.000Z'))).toBe('2026-10-09');
  });

  it('turns a calendar day into Kyiv day boundaries expressed in UTC', () => {
    // Summer time, UTC+3.
    expect(DateTime.dayStart('2026-08-12')).toBe('2026-08-11T21:00:00.000Z');
    expect(DateTime.nextDayStart('2026-08-12')).toBe('2026-08-12T21:00:00.000Z');
    expect(DateTime.dayEnd('2026-08-12')).toBe('2026-08-12T20:59:59.999Z');
    // Winter time, UTC+2.
    expect(DateTime.dayStart('2026-01-01')).toBe('2025-12-31T22:00:00.000Z');
  });

  it('keeps a day that crosses the clock change whole', () => {
    // Kyiv leaves summer time on 25.10.2026: that day lasts 25 hours.
    expect(DateTime.dayStart('2026-10-25')).toBe('2026-10-24T21:00:00.000Z');
    expect(DateTime.nextDayStart('2026-10-25')).toBe('2026-10-25T22:00:00.000Z');
  });

  it('refuses a value that is not a real calendar day', () => {
    for (const value of [undefined, null, '', '2026-02-31', '2026-08-12T10:00:00Z', 'завтра']) {
      expect(DateTime.dayStart(value)).toBeUndefined();
      expect(DateTime.dayEnd(value)).toBeUndefined();
    }
  });

  it('reduces an instant to the day it falls on in Kyiv', () => {
    expect(DateTime.toCalendarDate('2026-09-01T00:00:00.000Z')).toBe('2026-09-01');
    expect(DateTime.toCalendarDate('2026-09-01T22:30:00.000Z')).toBe('2026-09-02');
    expect(DateTime.toCalendarDate('2026-09-01')).toBe('2026-09-01');
    expect(DateTime.toCalendarDate(null)).toBeUndefined();
    expect(DateTime.toCalendarDate('not a date')).toBeUndefined();
  });

  it('moves a calendar date by whole days', () => {
    expect(DateTime.addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(DateTime.addDays('2026-03-01', -1)).toBe('2026-02-28');
  });
});
