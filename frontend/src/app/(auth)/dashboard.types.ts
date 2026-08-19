import type { DealStage } from '@/shared/constants';
import type { Id, IsoDateTime, MoneyWire } from '@/types/domain';

/**
 * Shapes of the analytics reports the dashboard reads. Only the fields the
 * overview actually shows are declared — the reports carry more, and copying
 * all of it here would tie this page to changes it does not care about.
 */

export interface DashboardRangeQuery {
  /** Start of the reporting window; the API closes it at "now" on its own. */
  readonly from: string;
}

export interface SalesSummaryTotals {
  readonly orderCount: number;
  readonly revenue: MoneyWire;
  readonly averageOrderValue: MoneyWire;
}

export interface SalesSummaryReport {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly totals: SalesSummaryTotals;
}

export interface DealFunnelStage {
  readonly stage: DealStage;
  readonly count: number;
  readonly amount: MoneyWire;
}

export interface DealFunnelReport {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly stages: readonly DealFunnelStage[];
}

export interface StockHealthQuery {
  readonly threshold: number;
  readonly limit: number;
}

export interface StockHealthRow {
  readonly productId: Id;
  readonly sku: string;
  readonly name: string;
  readonly warehouseId: Id;
  readonly warehouseCode: string;
  readonly quantityOnHand: number;
  readonly quantityReserved: number;
  readonly quantityAvailable: number;
}

export interface StockHealthReport {
  readonly threshold: number;
  readonly limit: number;
  readonly items: readonly StockHealthRow[];
}
