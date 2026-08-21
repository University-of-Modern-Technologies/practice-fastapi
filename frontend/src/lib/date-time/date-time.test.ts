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

  it('turns a wire value back into a picker value and back again', () => {
    const picker = DateTime.toPicker('2026-08-12');
    expect(picker).not.toBeNull();
    expect(DateTime.toWireDate(picker)).toBe('2026-08-12');
    expect(DateTime.toPicker(null)).toBeNull();
  });

  it('produces calendar dates for filter defaults', () => {
    expect(DateTime.today()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(DateTime.daysAgo(30)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(DateTime.daysAgo(30) < DateTime.today()).toBe(true);
  });
});
