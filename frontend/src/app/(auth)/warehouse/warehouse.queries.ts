'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import type { Id } from '@/types/domain';
import { WarehouseService } from './warehouse.service';
import type {
  CreateWarehouseInput,
  UpdateWarehouseInput,
  Warehouse,
  WarehouseListQuery,
} from './warehouse.types';

export const warehousesKeys = {
  all: ['warehouses'] as const,
  lists: () => [...warehousesKeys.all, 'list'] as const,
  list: (query: WarehouseListQuery) => [...warehousesKeys.lists(), query] as const,
  details: () => [...warehousesKeys.all, 'detail'] as const,
  detail: (id: Id) => [...warehousesKeys.details(), id] as const,
};

export const useWarehouses = (query: WarehouseListQuery) =>
  useQuery({
    queryKey: warehousesKeys.list(query),
    queryFn: () => WarehouseService.list(query),
  });

export const useWarehouse = (id: Id | undefined) =>
  useQuery({
    queryKey: warehousesKeys.detail(id ?? ''),
    queryFn: () => WarehouseService.get(id as Id),
    enabled: Boolean(id),
  });

/** One page is enough to fill a picker: the list of warehouses is short. */
const OPTIONS_QUERY: WarehouseListQuery = { page: 1, pageSize: 100, isActive: true };

/**
 * The pickers read one page and search inside it. That is right while the
 * directory is shorter than the page, and wrong the moment it is not — so the
 * cap is reported rather than hidden: `notice` is the line a picker shows under
 * its options once the answer says there are warehouses it did not receive.
 */
export const useWarehouseOptions = (): {
  options: readonly { value: string; label: string }[];
  isLoading: boolean;
  notice: string | undefined;
} => {
  const { data, isLoading } = useWarehouses(OPTIONS_QUERY);

  const options = useMemo(
    () =>
      (data?.items ?? []).map((item) => ({ value: item.id, label: `${item.code} — ${item.name}` })),
    [data],
  );

  const total = data?.total ?? 0;
  const notice =
    total > options.length
      ? `Показано ${options.length} активних складів із ${total} — решта в список не потрапила`
      : undefined;

  return { options, isLoading, notice };
};

export const useCreateWarehouse = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateWarehouseInput) => WarehouseService.create(input),
    onSuccess: (created: Warehouse) => {
      queryClient.setQueryData(warehousesKeys.detail(created.id), created);
      void queryClient.invalidateQueries({ queryKey: warehousesKeys.lists() });
    },
  });
};

export const useUpdateWarehouse = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateWarehouseInput) => WarehouseService.update(id, input),
    onSuccess: (updated: Warehouse) => {
      queryClient.setQueryData(warehousesKeys.detail(id), updated);
      void queryClient.invalidateQueries({ queryKey: warehousesKeys.lists() });
    },
  });
};
