/**
 * Bounds the list endpoints put on their query, as `openapi.json` states them.
 * A value past them is not narrowed by the API but refused with a 400, which
 * turns a long search typed into a picker, or a hand-edited `pageSize` in a
 * shared link, into a page that shows nothing but an error.
 */

/** Every paged endpoint: `pageSize` is `1…100`. */
export const MAX_PAGE_SIZE = 100;

/**
 * Every paged endpoint: `page` is `1…100` as well. Deep paging is not how a
 * list is read — past the hundredth page the way forward is a narrower filter,
 * and the API refuses the request rather than scanning that far.
 */
export const MAX_PAGE = 100;

/**
 * `search` on most lists is `1…160` characters. Two endpoints are narrower and
 * name their own bound: orders (64) and warehouses (120).
 */
export const SEARCH_MAX_LENGTH = 160;
export const ORDER_SEARCH_MAX_LENGTH = 64;
export const WAREHOUSE_SEARCH_MAX_LENGTH = 120;

/** Code unit range of the first half of a surrogate pair. */
const isHighSurrogate = (code: number): boolean => code >= 0xd800 && code <= 0xdbff;

/**
 * Shortens a search term to what the endpoint accepts instead of dropping it:
 * a term that ran past the limit still narrows the list, just less precisely.
 * The cut never splits an emoji or another character outside the BMP in half.
 */
export const clampSearch = (
  value: string | undefined,
  maxLength: number = SEARCH_MAX_LENGTH,
): string | undefined => {
  if (value === undefined || value.length <= maxLength) return value;
  const cut = value.slice(0, maxLength);
  return isHighSurrogate(cut.charCodeAt(cut.length - 1)) ? cut.slice(0, -1) : cut;
};

/** A page size inside `1…MAX_PAGE_SIZE`; an absent one stays absent. */
export const clampPageSize = (value: number | undefined): number | undefined => {
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return Math.min(Math.max(Math.trunc(value), 1), MAX_PAGE_SIZE);
};

/** A page number inside `1…MAX_PAGE`; an absent one stays absent. */
export const clampPage = (value: number | undefined): number | undefined => {
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return Math.min(Math.max(Math.trunc(value), 1), MAX_PAGE);
};

interface LimitedQuery {
  readonly search?: string | undefined;
  readonly page?: number | undefined;
  readonly pageSize?: number | undefined;
}

/**
 * Applies the bounds to a list query on its way out. Called in each service's
 * `list`, the one place every caller passes through — the page reading its
 * query string and the reference picker passing whatever was typed alike.
 */
export const withListLimits = <Q extends LimitedQuery>(
  query: Q,
  searchMaxLength: number = SEARCH_MAX_LENGTH,
): Q => {
  const search = clampSearch(query.search, searchMaxLength);
  const page = clampPage(query.page);
  const pageSize = clampPageSize(query.pageSize);
  return {
    ...query,
    ...(search === undefined ? {} : { search }),
    ...(page === undefined ? {} : { page }),
    ...(pageSize === undefined ? {} : { pageSize }),
  };
};
