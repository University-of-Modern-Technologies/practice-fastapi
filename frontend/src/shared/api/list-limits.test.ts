import { describe, expect, it } from 'vitest';
import {
  MAX_PAGE,
  MAX_PAGE_SIZE,
  ORDER_SEARCH_MAX_LENGTH,
  SEARCH_MAX_LENGTH,
  clampPage,
  clampPageSize,
  clampSearch,
  withListLimits,
} from './list-limits';

describe('list limits', () => {
  // A term past `maxLength` is a 400, not a narrower search: it is shortened
  // so the list still narrows by what fits.
  it('shortens a search term to the length the endpoint accepts', () => {
    expect(clampSearch('x'.repeat(200))).toHaveLength(SEARCH_MAX_LENGTH);
    expect(clampSearch('x'.repeat(80), ORDER_SEARCH_MAX_LENGTH)).toHaveLength(64);
    expect(clampSearch('коротко')).toBe('коротко');
    expect(clampSearch(undefined)).toBeUndefined();
  });

  it('never leaves half of a character outside the BMP at the cut', () => {
    const term = `${'x'.repeat(SEARCH_MAX_LENGTH - 1)}😀`;

    const clamped = clampSearch(term) ?? '';

    expect(clamped.length).toBeLessThanOrEqual(SEARCH_MAX_LENGTH);
    expect(clamped).toBe('x'.repeat(SEARCH_MAX_LENGTH - 1));
  });

  it('keeps the page size inside 1…100', () => {
    expect(clampPageSize(500)).toBe(MAX_PAGE_SIZE);
    expect(clampPageSize(0)).toBe(1);
    expect(clampPageSize(20)).toBe(20);
    expect(clampPageSize(undefined)).toBeUndefined();
  });

  // `page=500` in a shared link is a 400 from the API, not an empty page.
  it('keeps the page number inside 1…100', () => {
    expect(clampPage(500)).toBe(MAX_PAGE);
    expect(clampPage(100)).toBe(100);
    expect(clampPage(0)).toBe(1);
    expect(clampPage(7.9)).toBe(7);
    expect(clampPage(undefined)).toBeUndefined();
  });

  it('applies every bound to a query and leaves the rest alone', () => {
    expect(
      withListLimits({ page: 3, pageSize: 1000, search: 'y'.repeat(300), stage: 'LEAD' }),
    ).toEqual({ page: 3, pageSize: 100, search: 'y'.repeat(160), stage: 'LEAD' });
    expect(withListLimits({ page: 250, pageSize: 20 })).toEqual({ page: 100, pageSize: 20 });
    const untouched: { readonly page: number; readonly search?: string } = { page: 1 };
    expect(withListLimits(untouched)).toEqual({ page: 1 });
  });
});
