/**
 * Primitives shared by every domain module. Entity shapes themselves live next
 * to the module that owns them — only what more than one module needs is here.
 */

/** UUID as it travels on the wire. Named for readability, not for safety. */
export type Id = string;

/** `Decimal(14, 2)` serialised as a string, e.g. `"1234.50"`. Never a number. */
export type MoneyWire = string;

/** ISO 8601 instant with milliseconds, e.g. `"2026-08-12T15:23:45.123Z"`. */
export type IsoDateTime = string;

/** Calendar date without a zone, e.g. `"2026-08-12"`. */
export type IsoDate = string;

/** ISO 4217 code, e.g. `"USD"`. */
export type CurrencyCode = string;

/** Present on every record the API returns. */
export interface Timestamps {
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/**
 * Carried by entities under optimistic concurrency control. The value read with
 * the record is sent back on write; a mismatch answers 409 rather than
 * overwriting whatever someone else saved in between.
 */
export interface Versioned {
  readonly version: number;
}

/** Error codes the client branches on. Anything else is reported generically. */
export const ERROR_CODE = {
  validation: 'VALIDATION_ERROR',
  contactChannelRequired: 'CONTACT_CHANNEL_REQUIRED',
  contactDuplicate: 'CONTACT_DUPLICATE',
  productSkuImmutable: 'PRODUCT_SKU_IMMUTABLE',
  warehouseCodeImmutable: 'WAREHOUSE_CODE_IMMUTABLE',
  invalidStockAdjustment: 'INVALID_STOCK_ADJUSTMENT',
  stockAdjustmentNoteRequired: 'STOCK_ADJUSTMENT_NOTE_REQUIRED',
  roleAlreadyExists: 'ROLE_ALREADY_EXISTS',
  invalidSettingValue: 'INVALID_SETTING_VALUE',
  unknownPermission: 'UNKNOWN_PERMISSION',
  dealConflict: 'DEAL_CONCURRENT_MODIFICATION',
  productConflict: 'PRODUCT_CONCURRENT_MODIFICATION',
  orderConflict: 'ORDER_CONCURRENT_MODIFICATION',
  dealTransition: 'INVALID_DEAL_STAGE_TRANSITION',
  orderTransition: 'INVALID_ORDER_STATUS_TRANSITION',
  orderNotEditable: 'ORDER_NOT_EDITABLE',
  orderHasNoItems: 'ORDER_HAS_NO_ITEMS',
  orderItemDuplicate: 'ORDER_ITEM_DUPLICATE',
  insufficientStock: 'INSUFFICIENT_STOCK',
  insufficientReservation: 'INSUFFICIENT_RESERVATION',
  productInactive: 'PRODUCT_INACTIVE',
  productSkuTaken: 'PRODUCT_SKU_TAKEN',
  warehouseCodeTaken: 'WAREHOUSE_CODE_TAKEN',
  warehouseInactive: 'WAREHOUSE_INACTIVE',
  emailAlreadyExists: 'EMAIL_ALREADY_EXISTS',
  unknownSettingKey: 'UNKNOWN_SETTING_KEY',
} as const;

export type ErrorCode = (typeof ERROR_CODE)[keyof typeof ERROR_CODE];

/**
 * Shape of `details` on a 400 `VALIDATION_ERROR`. Both backends flatten their
 * validator the same way, which is what lets a message land on its own field.
 */
export interface ValidationDetails {
  readonly formErrors?: readonly string[];
  readonly fieldErrors?: {
    readonly body?: readonly string[];
    readonly query?: readonly string[];
    readonly params?: readonly string[];
  };
}
