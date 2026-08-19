'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useMemo } from 'react';
import type { ListQuery } from '@/shared/api';

export type SortOrder = 'asc' | 'desc';

export interface ListParamsDefaults {
  readonly page?: number;
  readonly pageSize?: number;
  readonly sortBy?: string;
  readonly sortOrder?: SortOrder;
}

export type ListParams<F extends string = never> = Required<Pick<ListQuery, 'page' | 'pageSize'>> &
  Readonly<{ sortBy?: string; sortOrder?: SortOrder }> &
  Readonly<Partial<Record<F, string>>>;

export type ListParamsPatch<F extends string = never> = Readonly<
  Partial<Record<F | 'sortBy' | 'sortOrder' | 'page' | 'pageSize', string | number | undefined>>
>;

interface UseListParamsOptions<F extends string> {
  /** Names of the filters this list understands. Anything else is ignored. */
  readonly filters?: readonly F[];
  readonly defaults?: ListParamsDefaults;
}

const DEFAULT_PAGE = 1;
const DEFAULT_PAGE_SIZE = 20;

const readNumber = (value: string | null, fallback: number): number => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
};

/**
 * Keeps the state of a list — page, sorting, filters — in the query string.
 * A list the user has narrowed down is then just a link: it can be bookmarked,
 * reloaded, or pasted to a colleague and it opens showing the same rows.
 */
export const useListParams = <F extends string = never>(
  options: UseListParamsOptions<F> = {},
): {
  params: ListParams<F>;
  setParams: (patch: ListParamsPatch<F>) => void;
  resetParams: () => void;
} => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const { filters, defaults } = options;
  const defaultPage = defaults?.page ?? DEFAULT_PAGE;
  const defaultPageSize = defaults?.pageSize ?? DEFAULT_PAGE_SIZE;
  const defaultSortBy = defaults?.sortBy;
  const defaultSortOrder = defaults?.sortOrder;

  // Depending on the string keeps the memo stable across renders that did not
  // touch the query; `searchParams` itself is a new object every time.
  const search = searchParams.toString();

  const params = useMemo(() => {
    const current = new URLSearchParams(search);
    const sortOrder = current.get('sortOrder');

    const result: Record<string, string | number | undefined> = {
      page: readNumber(current.get('page'), defaultPage),
      pageSize: readNumber(current.get('pageSize'), defaultPageSize),
      sortBy: current.get('sortBy') ?? defaultSortBy,
      sortOrder: sortOrder === 'asc' || sortOrder === 'desc' ? sortOrder : defaultSortOrder,
    };

    for (const filter of filters ?? []) {
      const value = current.get(filter);
      if (value !== null && value !== '') result[filter] = value;
    }

    return result as ListParams<F>;
  }, [search, filters, defaultPage, defaultPageSize, defaultSortBy, defaultSortOrder]);

  const setParams = useCallback(
    (patch: ListParamsPatch<F>) => {
      const next = new URLSearchParams(search);

      for (const [key, value] of Object.entries(patch)) {
        // An empty filter leaves the query rather than becoming "undefined".
        if (value === undefined || value === null || value === '') next.delete(key);
        else next.set(key, String(value));
      }

      // Narrowing the list while sitting on page 7 would show an empty table;
      // any change other than paging itself starts the result over.
      const changedBeyondPaging = Object.keys(patch).some((key) => key !== 'page');
      if (changedBeyondPaging && patch.page === undefined) next.delete('page');

      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [search, pathname, router],
  );

  const resetParams = useCallback(() => {
    router.replace(pathname, { scroll: false });
  }, [pathname, router]);

  return { params, setParams, resetParams };
};
