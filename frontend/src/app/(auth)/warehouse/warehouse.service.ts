import { http, type Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import type {
  CreateWarehouseInput,
  UpdateWarehouseInput,
  Warehouse,
  WarehouseListQuery,
} from './warehouse.types';

const ROUTES = {
  list: '/warehouse/warehouses',
  byId: (id: Id) => `/warehouse/warehouses/${id}`,
} as const;

export const WarehouseService = {
  list: (query: WarehouseListQuery): Promise<Page<Warehouse>> =>
    http.get<Page<Warehouse>>(ROUTES.list, {
      params: {
        page: query.page,
        pageSize: query.pageSize,
        search: query.search,
        isActive: query.isActive,
      },
    }),

  get: (id: Id): Promise<Warehouse> => http.get<Warehouse>(ROUTES.byId(id)),

  create: (input: CreateWarehouseInput): Promise<Warehouse> =>
    http.post<Warehouse>(ROUTES.list, input),

  /** The code is omitted on purpose — the API treats it as immutable. */
  update: (id: Id, input: UpdateWarehouseInput): Promise<Warehouse> =>
    http.patch<Warehouse>(ROUTES.byId(id), input),
};
