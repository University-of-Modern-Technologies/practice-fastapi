'use client';

import { useQuery } from '@tanstack/react-query';
import { MovementsService } from './movements.service';
import type { MovementListQuery } from './warehouse.types';

export const movementsKeys = {
  all: ['stock-movements'] as const,
  lists: () => [...movementsKeys.all, 'list'] as const,
  list: (query: MovementListQuery) => [...movementsKeys.lists(), query] as const,
};

export const useStockMovements = (query: MovementListQuery) =>
  useQuery({
    queryKey: movementsKeys.list(query),
    queryFn: () => MovementsService.list(query),
  });
