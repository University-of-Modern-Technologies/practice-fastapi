import type { CurrencyCode, Id, MoneyWire, Timestamps, Versioned } from '@/types/domain';

/** A catalogue entry as the API returns it. `unitPrice` is a string, never a number. */
export interface Product extends Timestamps, Versioned {
  readonly id: Id;
  readonly sku: string;
  readonly name: string;
  readonly description: string | null;
  readonly category: string | null;
  readonly unitPrice: MoneyWire;
  readonly currency: CurrencyCode;
  readonly isActive: boolean;
}

/** The only columns the API agrees to order by; anything else answers 400. */
export const PRODUCT_SORT_FIELDS = [
  'createdAt',
  'updatedAt',
  'name',
  'sku',
  'unitPrice',
  'category',
] as const;

export type ProductSortField = (typeof PRODUCT_SORT_FIELDS)[number];

export const isProductSortField = (value: string | undefined): value is ProductSortField =>
  value !== undefined && (PRODUCT_SORT_FIELDS as readonly string[]).includes(value);

/** Filters this list understands. Also the set `useListParams` keeps in the URL. */
export const PRODUCT_FILTERS = ['search', 'category', 'isActive', 'minPrice', 'maxPrice'] as const;

export type ProductFilter = (typeof PRODUCT_FILTERS)[number];

export interface ProductListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly category?: string;
  readonly isActive?: boolean;
  readonly minPrice?: MoneyWire;
  readonly maxPrice?: MoneyWire;
  readonly sortBy?: ProductSortField;
  readonly sortOrder?: 'asc' | 'desc';
}

export interface CreateProductInput {
  readonly sku: string;
  readonly name: string;
  readonly description?: string;
  readonly category?: string;
  readonly unitPrice: MoneyWire;
  readonly currency?: CurrencyCode;
  readonly isActive?: boolean;
}

/**
 * `sku` is deliberately absent: the catalogue identifier is fixed once the
 * product exists, and sending it answers 400 `PRODUCT_SKU_IMMUTABLE`.
 */
export interface UpdateProductInput {
  readonly version: number;
  readonly name?: string;
  readonly description?: string | null;
  readonly category?: string | null;
  readonly unitPrice?: MoneyWire;
  readonly currency?: CurrencyCode;
  readonly isActive?: boolean;
}

/** Error codes this module reacts to by name rather than by status alone. */
export const PRODUCT_ERROR = {
  conflict: 'PRODUCT_CONCURRENT_MODIFICATION',
  skuTaken: 'PRODUCT_SKU_TAKEN',
  skuImmutable: 'PRODUCT_SKU_IMMUTABLE',
} as const;
