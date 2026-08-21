'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/shared/api';
import type { Id } from '@/types/domain';
import { movementsKeys } from './movements.queries';
import { StockService } from './stock.service';
import type { StockListQuery, StockOperationRequest } from './warehouse.types';

export const stockKeys = {
  all: ['stock'] as const,
  lists: () => [...stockKeys.all, 'list'] as const,
  list: (query: StockListQuery) => [...stockKeys.lists(), query] as const,
  details: () => [...stockKeys.all, 'detail'] as const,
  detail: (warehouseId: Id, productId: Id) =>
    [...stockKeys.details(), warehouseId, productId] as const,
};

/**
 * A refused operation is not a generic failure: each code names a condition the
 * user can act on, so it gets its own sentence instead of «перевірте дані».
 */
const OPERATION_ERRORS: Readonly<Record<string, string>> = {
  INSUFFICIENT_STOCK: 'Недостатньо залишку на складі',
  INSUFFICIENT_RESERVATION: 'Недостатньо зарезервованої кількості',
  WAREHOUSE_INACTIVE: 'Склад неактивний — операції з ним заборонені',
  INVALID_STOCK_ADJUSTMENT: 'Коригування не може дорівнювати нулю',
  STOCK_ADJUSTMENT_NOTE_REQUIRED: 'Коригування потребує коментаря',
};

export const describeStockError = (error: unknown): string | null =>
  error instanceof ApiError ? (OPERATION_ERRORS[error.code] ?? null) : null;

export const useStockLevels = (query: StockListQuery) =>
  useQuery({
    queryKey: stockKeys.list(query),
    queryFn: () => StockService.list(query),
  });

export const useStockLevel = (warehouseId: Id | undefined, productId: Id | undefined) =>
  useQuery({
    queryKey: stockKeys.detail(warehouseId ?? '', productId ?? ''),
    queryFn: () => StockService.get(warehouseId as Id, productId as Id),
    enabled: Boolean(warehouseId && productId),
  });

export const useStockOperation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: StockOperationRequest) => StockService.run(request),
    onSuccess: (level) => {
      queryClient.setQueryData(stockKeys.detail(level.warehouseId, level.productId), level);
      void queryClient.invalidateQueries({ queryKey: stockKeys.lists() });
      // Every operation writes a movement; without this the ledger would show
      // the change only after a manual reload.
      void queryClient.invalidateQueries({ queryKey: movementsKeys.lists() });
    },
  });
};
