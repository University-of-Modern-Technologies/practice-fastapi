import type { DealStage } from '@/shared/constants';
import type { Id, IsoDateTime, MoneyWire } from '@/types/domain';

/** Bucket width the sales report groups orders by. */
export const ANALYTICS_PERIODS = ['day', 'week', 'month'] as const;
export type AnalyticsPeriod = (typeof ANALYTICS_PERIODS)[number];

export const isAnalyticsPeriod = (value: string | undefined): value is AnalyticsPeriod =>
  value !== undefined && (ANALYTICS_PERIODS as readonly string[]).includes(value);

/** Half-open interval `[from, to)`, both ISO 8601 instants, as the API reads it. */
export interface DateRange {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
}

/** The same interval as it lives in the query string — calendar days the user picked. */
export interface CalendarRange {
  readonly from: string;
  readonly to: string;
}

export interface SalesSummaryQuery extends DateRange {
  readonly period: AnalyticsPeriod;
  readonly ownerId?: Id;
}

export interface SalesSummaryBucket {
  readonly bucketStart: IsoDateTime;
  readonly orderCount: number;
  readonly revenue: MoneyWire;
}

export interface SalesSummaryReport {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly period: AnalyticsPeriod;
  readonly totals: {
    readonly orderCount: number;
    readonly revenue: MoneyWire;
    readonly averageOrderValue: MoneyWire;
  };
  readonly series: readonly SalesSummaryBucket[];
}

export interface DealFunnelQuery extends DateRange {
  readonly ownerId?: Id;
}

export interface DealFunnelStage {
  readonly stage: DealStage;
  readonly count: number;
  readonly amount: MoneyWire;
}

export interface DealFunnelConversion {
  readonly from: DealStage;
  readonly to: DealStage;
  /** Ratio in `[0, 1]` with four decimals — a share, not a percentage. */
  readonly rate: number;
}

export interface DealFunnelReport {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly stages: readonly DealFunnelStage[];
  readonly conversions: readonly DealFunnelConversion[];
}

export interface TopProductsQuery extends DateRange {
  readonly limit: number;
}

export interface TopProductRow {
  readonly productId: Id;
  readonly sku: string;
  readonly name: string;
  readonly quantity: number;
  readonly revenue: MoneyWire;
}

export interface TopProductsReport {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly limit: number;
  readonly items: readonly TopProductRow[];
}

export interface OwnerPerformanceQuery extends DateRange {
  readonly limit: number;
}

export interface OwnerPerformanceRow {
  readonly ownerId: Id;
  readonly name: string | null;
  readonly email: string | null;
  readonly dealCount: number;
  readonly dealAmount: MoneyWire;
  readonly wonDealCount: number;
  readonly wonDealAmount: MoneyWire;
  /** Ratio in `[0, 1]`, like the funnel conversions. */
  readonly winRate: number;
  readonly orderCount: number;
  readonly orderRevenue: MoneyWire;
}

export interface OwnerPerformanceReport {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly items: readonly OwnerPerformanceRow[];
}

/** Stock health looks at the present, so it carries no period at all. */
export interface StockHealthQuery {
  readonly threshold: number;
  readonly limit: number;
  readonly warehouseId?: Id;
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
