import type { StockMovementType } from '@/shared/constants';
import type { Id, IsoDateTime, Timestamps, Versioned } from '@/types/domain';

export interface Warehouse extends Timestamps {
  readonly id: Id;
  readonly code: string;
  readonly name: string;
  readonly isActive: boolean;
}

export type WarehouseListQuery = {
  readonly page: number;
  readonly pageSize: number;
  readonly search?: string | undefined;
  readonly isActive?: boolean | undefined;
};

export interface CreateWarehouseInput {
  readonly code: string;
  readonly name: string;
  readonly isActive?: boolean | undefined;
}

/**
 * The code is fixed at creation — sending a different one answers 400
 * `WAREHOUSE_CODE_IMMUTABLE` — so it is not part of the update at all.
 */
export interface UpdateWarehouseInput {
  readonly name?: string | undefined;
  readonly isActive?: boolean | undefined;
}

export interface StockLevel extends Timestamps, Versioned {
  readonly id: Id;
  readonly warehouseId: Id;
  readonly productId: Id;
  readonly quantityOnHand: number;
  readonly quantityReserved: number;
  /** Derived by the API as on-hand minus reserved; never written back. */
  readonly quantityAvailable: number;
}

export type StockListQuery = {
  readonly page: number;
  readonly pageSize: number;
  readonly warehouseId?: string | undefined;
  readonly productId?: string | undefined;
  readonly lowStockThreshold?: number | undefined;
};

export interface StockMovement {
  readonly id: Id;
  readonly warehouseId: Id;
  readonly productId: Id;
  readonly type: StockMovementType;
  readonly quantity: number;
  readonly referenceType: string | null;
  readonly referenceId: string | null;
  readonly actorId: Id | null;
  readonly note: string | null;
  /** The ledger only ever grows, so a movement has no `updatedAt`. */
  readonly createdAt: IsoDateTime;
}

export type MovementListQuery = {
  readonly page: number;
  readonly pageSize: number;
  readonly warehouseId?: string | undefined;
  readonly productId?: string | undefined;
  readonly type?: StockMovementType | undefined;
  readonly referenceType?: string | undefined;
  readonly referenceId?: string | undefined;
  readonly createdFrom?: string | undefined;
  readonly createdTo?: string | undefined;
};

export const STOCK_OPERATIONS = ['receive', 'issue', 'reserve', 'release', 'adjust'] as const;
export type StockOperation = (typeof STOCK_OPERATIONS)[number];

export const STOCK_OPERATION_LABEL: Readonly<Record<StockOperation, string>> = {
  receive: 'Оприбуткування',
  issue: 'Списання',
  reserve: 'Резервування',
  release: 'Зняття резерву',
  adjust: 'Коригування',
};

interface StockTarget {
  readonly warehouseId: Id;
  readonly productId: Id;
}

export interface ReceiveStockInput extends StockTarget {
  readonly quantity: number;
  readonly referenceType?: string | undefined;
  readonly referenceId?: string | undefined;
  readonly note?: string | undefined;
}

export interface IssueStockInput extends ReceiveStockInput {
  /** When set, the issue consumes an existing reservation and must name it. */
  readonly fromReservation?: boolean | undefined;
}

export interface ReserveStockInput extends StockTarget {
  readonly quantity: number;
  /** A reservation is always held on behalf of something. */
  readonly referenceType: string;
  readonly referenceId: string;
  readonly note?: string | undefined;
}

export type ReleaseStockInput = ReserveStockInput;

export interface AdjustStockInput extends StockTarget {
  /** Signed correction; zero records nothing and is rejected. */
  readonly delta: number;
  /** Mandatory: an unexplained correction is not auditable. */
  readonly note: string;
  readonly referenceType?: string | undefined;
  readonly referenceId?: string | undefined;
}

/**
 * Ties an operation to the only body the API accepts for it. Keeping them in
 * one union means a caller cannot post a `reserve` body to `receive`.
 */
export type StockOperationRequest =
  | { readonly operation: 'receive'; readonly input: ReceiveStockInput }
  | { readonly operation: 'issue'; readonly input: IssueStockInput }
  | { readonly operation: 'reserve'; readonly input: ReserveStockInput }
  | { readonly operation: 'release'; readonly input: ReleaseStockInput }
  | { readonly operation: 'adjust'; readonly input: AdjustStockInput };
