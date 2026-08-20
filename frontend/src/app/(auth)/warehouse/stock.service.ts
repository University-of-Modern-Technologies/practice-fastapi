import { http, type Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import type {
  StockLevel,
  StockListQuery,
  StockOperation,
  StockOperationRequest,
} from './warehouse.types';

const ROUTES = {
  list: '/warehouse/stock',
  byTarget: (warehouseId: Id, productId: Id) => `/warehouse/stock/${warehouseId}/${productId}`,
  operation: (operation: StockOperation) => `/warehouse/stock/${operation}`,
} as const;

export const StockService = {
  list: (query: StockListQuery): Promise<Page<StockLevel>> =>
    http.get<Page<StockLevel>>(ROUTES.list, {
      params: {
        page: query.page,
        pageSize: query.pageSize,
        warehouseId: query.warehouseId,
        productId: query.productId,
        lowStockThreshold: query.lowStockThreshold,
      },
    }),

  get: (warehouseId: Id, productId: Id): Promise<StockLevel> =>
    http.get<StockLevel>(ROUTES.byTarget(warehouseId, productId)),

  /**
   * All five operations answer with the level as it stands after the write, so
   * the caller never has to re-read to learn the new numbers. They share one
   * entry point because the union already pairs each body with its own path.
   */
  run: ({ operation, input }: StockOperationRequest): Promise<StockLevel> =>
    http.post<StockLevel>(ROUTES.operation(operation), input),
};
