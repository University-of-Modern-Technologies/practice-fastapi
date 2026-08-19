import type { ListParams } from '@/shared/hooks';

type SortOrder = 'asc' | 'desc';

type ListQueryValue = string | number | boolean | SortOrder;

/**
 * Every list filter arrives from the query string as text, or is absent
 * altogether — `useListParams` never puts an empty string or a raw
 * `undefined` in. Narrowing it into the shape an endpoint expects belongs
 * here rather than at each call site: an enum value the API does not know, an
 * out-of-range number or a sort column it never agreed to would otherwise
 * reach the request and turn a hand-edited link into a 400.
 *
 * `page` and `pageSize` are copied straight through — `useListParams` already
 * guarantees they are positive integers before a caller ever sees them.
 */
class ListQueryBuilder<F extends string> {
  private readonly params: ListParams<F>;
  private readonly result: Record<string, ListQueryValue> = {};

  constructor(params: ListParams<F>) {
    this.params = params;
    this.result.page = params.page;
    this.result.pageSize = params.pageSize;
  }

  /**
   * Keeps a non-empty filter as text. `maxLength` truncates rather than
   * drops — a search term that ran past what the API accepts still narrows
   * the list, just less precisely.
   */
  text(key: F, options: { readonly maxLength?: number } = {}): this {
    const raw = this.params[key];
    if (typeof raw !== 'string' || raw === '') return this;
    this.result[key] = options.maxLength === undefined ? raw : raw.slice(0, options.maxLength);
    return this;
  }

  /** Keeps the filter only when it names one of the values the API accepts. */
  oneOf<V extends string>(key: F, allowed: readonly V[]): this {
    const raw = this.params[key];
    if (typeof raw === 'string' && (allowed as readonly string[]).includes(raw)) {
      this.result[key] = raw;
    }
    return this;
  }

  /** Reads the two textual values a checkbox filter can hold; anything else is dropped. */
  boolean(key: F): this {
    const raw = this.params[key];
    if (raw === 'true' || raw === 'false') this.result[key] = raw === 'true';
    return this;
  }

  /**
   * Keeps a whole number inside the given bounds. Text that fails to parse,
   * a fraction, or a value outside the bounds is dropped rather than clamped
   * — a bound the caller cannot see silently applied would be worse than none.
   */
  integer(key: F, bounds: { readonly min?: number; readonly max?: number } = {}): this {
    const raw = this.params[key];
    if (typeof raw !== 'string' || raw === '') return this;
    const parsed = Number(raw);
    if (!Number.isInteger(parsed)) return this;
    if (bounds.min !== undefined && parsed < bounds.min) return this;
    if (bounds.max !== undefined && parsed > bounds.max) return this;
    this.result[key] = parsed;
    return this;
  }

  /**
   * Keeps the sort column only when the API agrees to order by it. The
   * direction needs no narrowing here — `useListParams` already restricts it
   * to `'asc' | 'desc'` before it reaches this builder.
   */
  sort<V extends string>(isSortField: (value: string | undefined) => value is V): this {
    if (isSortField(this.params.sortBy)) this.result.sortBy = this.params.sortBy;
    if (this.params.sortOrder !== undefined) this.result.sortOrder = this.params.sortOrder;
    return this;
  }

  /** Casts to the endpoint's own query type: only valid, narrowed keys were ever set above. */
  build<TOut>(): TOut {
    return this.result as unknown as TOut;
  }
}

export const listQuery = <F extends string>(params: ListParams<F>): ListQueryBuilder<F> =>
  new ListQueryBuilder<F>(params);
