import { http, type Page } from '@/shared/api';
import type { MovementListQuery, StockMovement } from './warehouse.types';

const ROUTES = {
  list: '/warehouse/movements',
} as const;

/**
 * The ledger is append-only: the API exposes no update or delete verb, so this
 * service reads and nothing more. A mistake is corrected by an adjustment.
 */
export const MovementsService = {
  list: (query: MovementListQuery): Promise<Page<StockMovement>> =>
    http.get<Page<StockMovement>>(ROUTES.list, {
      params: {
        page: query.page,
        pageSize: query.pageSize,
        warehouseId: query.warehouseId,
        productId: query.productId,
        type: query.type,
        referenceType: query.referenceType,
        referenceId: query.referenceId,
        createdFrom: query.createdFrom,
        createdTo: query.createdTo,
      },
    }),
};
