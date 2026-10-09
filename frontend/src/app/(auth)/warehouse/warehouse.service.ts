import { http, type Page } from '@/shared/api';
import { WAREHOUSE_SEARCH_MAX_LENGTH, clampPageSize, clampSearch } from '@/shared/api/list-limits';
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
        pageSize: clampPageSize(query.pageSize),
        search: clampSearch(query.search, WAREHOUSE_SEARCH_MAX_LENGTH),
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
