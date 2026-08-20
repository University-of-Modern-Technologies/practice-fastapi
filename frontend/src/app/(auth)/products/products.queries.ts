'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import { ProductsService } from './products.service';
import type {
  CreateProductInput,
  Product,
  ProductListQuery,
  UpdateProductInput,
} from './products.types';

export const productsKeys = {
  all: ['products'] as const,
  lists: () => [...productsKeys.all, 'list'] as const,
  list: (params: ProductListQuery) => [...productsKeys.lists(), params] as const,
  details: () => [...productsKeys.all, 'detail'] as const,
  detail: (id: Id) => [...productsKeys.details(), id] as const,
};

export const useProducts = (query: ProductListQuery) =>
  useQuery<Page<Product>>({
    queryKey: productsKeys.list(query),
    queryFn: ({ signal }) => ProductsService.list(query, signal),
    // Paging swaps one page for the next in place instead of blanking the table.
    placeholderData: keepPreviousData,
  });

export const useProduct = (id: Id) =>
  useQuery<Product>({
    queryKey: productsKeys.detail(id),
    queryFn: ({ signal }) => ProductsService.getById(id, signal),
    enabled: id !== '',
  });

/** A catalogue position is recognised by its article first, its name second. */
export const productLabel = (product: Product): string => `${product.sku} — ${product.name}`;

/** One page is what a picker shows; the term narrows it on the server. */
const REFERENCE_PAGE_SIZE = 20;

/** Feeds a reference picker. Withdrawn positions are never offered for a new line. */
export const useProductOptions = (
  search: string,
): { items: readonly Product[]; isFetching: boolean } => {
  const { data, isFetching } = useProducts({
    page: 1,
    pageSize: REFERENCE_PAGE_SIZE,
    isActive: true,
    sortBy: 'name',
    sortOrder: 'asc',
    ...(search ? { search } : {}),
  });

  return { items: data?.items ?? [], isFetching };
};

export const useResolvedProduct = (id: Id | undefined): Product | undefined =>
  useProduct(id ?? '').data;

export const useCreateProduct = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateProductInput) => ProductsService.create(input),
    onSuccess: (product) => {
      queryClient.setQueryData(productsKeys.detail(product.id), product);
      void queryClient.invalidateQueries({ queryKey: productsKeys.lists() });
    },
  });
};

export const useUpdateProduct = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateProductInput) => ProductsService.update(id, input),
    onSuccess: (product) => {
      // The answer already carries the bumped version — caching it means the
      // next save sends the current one without an extra read.
      queryClient.setQueryData(productsKeys.detail(id), product);
      void queryClient.invalidateQueries({ queryKey: productsKeys.lists() });
    },
  });
};

export const useDeleteProduct = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (version: number) => ProductsService.remove(id, version),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: productsKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: productsKeys.lists() });
    },
  });
};
