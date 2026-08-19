import { ApiError } from '@/shared/api';
import type { OrderStatus } from '@/shared/constants';
import type { CurrencyCode, Id, MoneyWire, Timestamps, Versioned } from '@/types/domain';

/**
 * A line of an order. `sku` and `name` are snapshots taken from the catalogue
 * when the line was added, so a later rename of the product does not rewrite
 * the history of an order that has already been placed.
 */
export interface OrderItem extends Timestamps {
  readonly id: Id;
  readonly orderId: Id;
  readonly productId: Id;
  readonly sku: string;
  readonly name: string;
  readonly quantity: number;
  readonly unitPrice: MoneyWire;
  readonly lineTotal: MoneyWire;
}

/**
 * An order as the API returns it. Every monetary field is a string and is
 * derived on the server from the lines — the client never computes a total it
 * then sends back.
 */
export interface Order extends Timestamps, Versioned {
  readonly id: Id;
  readonly orderNumber: string;
  readonly ownerId: Id;
  readonly contactId: Id | null;
  readonly dealId: Id | null;
  readonly status: OrderStatus;
  readonly currency: CurrencyCode;
  readonly subtotal: MoneyWire;
  readonly discountTotal: MoneyWire;
  readonly taxTotal: MoneyWire;
  readonly total: MoneyWire;
  readonly notes: string | null;
  readonly placedAt: string | null;
  readonly items: readonly OrderItem[];
}

/** The only columns the API agrees to order by; anything else answers 400. */
export const ORDER_SORT_FIELDS = [
  'createdAt',
  'updatedAt',
  'orderNumber',
  'total',
  'placedAt',
  'status',
] as const;

export type OrderSortField = (typeof ORDER_SORT_FIELDS)[number];

export const isOrderSortField = (value: string | undefined): value is OrderSortField =>
  value !== undefined && (ORDER_SORT_FIELDS as readonly string[]).includes(value);

/** Filters this list understands. Also the set `useListParams` keeps in the URL. */
export const ORDER_FILTERS = [
  'search',
  'ownerId',
  'contactId',
  'dealId',
  'status',
  'minTotal',
  'maxTotal',
] as const;

export type OrderFilter = (typeof ORDER_FILTERS)[number];

export interface OrderListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly ownerId?: Id;
  readonly contactId?: Id;
  readonly dealId?: Id;
  readonly status?: OrderStatus;
  readonly minTotal?: MoneyWire;
  readonly maxTotal?: MoneyWire;
  readonly sortBy?: OrderSortField;
  readonly sortOrder?: 'asc' | 'desc';
}

/** One line of a brand-new order, sent inside the create request. */
export interface CreateOrderItemInput {
  readonly productId: Id;
  readonly quantity: number;
}

/**
 * `orderNumber`, `status` and the totals are deliberately absent: the first two
 * are allocated by the server and the totals are derived from the lines, so
 * sending any of them is rejected rather than honoured.
 */
export interface CreateOrderInput {
  readonly ownerId?: Id;
  readonly contactId?: Id;
  readonly dealId?: Id;
  readonly currency?: CurrencyCode;
  readonly discountTotal?: MoneyWire;
  readonly taxTotal?: MoneyWire;
  readonly notes?: string;
  readonly items?: readonly CreateOrderItemInput[];
}

/** Carries the version it read; a stale one answers 409 instead of overwriting. */
export interface UpdateOrderInput {
  readonly version: number;
  readonly ownerId?: Id;
  readonly contactId?: Id | null;
  readonly dealId?: Id | null;
  readonly currency?: CurrencyCode;
  readonly discountTotal?: MoneyWire;
  readonly taxTotal?: MoneyWire;
  readonly notes?: string | null;
}

export interface AddOrderItemInput {
  readonly version: number;
  readonly productId: Id;
  readonly quantity: number;
}

export interface UpdateOrderItemInput {
  readonly version: number;
  readonly quantity: number;
}

export interface TransitionOrderInput {
  readonly version: number;
  readonly status: OrderStatus;
}

/** Error codes this module reacts to by name rather than by status alone. */
export const ORDER_ERROR = {
  conflict: 'ORDER_CONCURRENT_MODIFICATION',
  notEditable: 'ORDER_NOT_EDITABLE',
  noItems: 'ORDER_HAS_NO_ITEMS',
  itemDuplicate: 'ORDER_ITEM_DUPLICATE',
  currencyMismatch: 'ORDER_CURRENCY_MISMATCH',
  invalidTransition: 'INVALID_ORDER_STATUS_TRANSITION',
  insufficientStock: 'INSUFFICIENT_STOCK',
  productInactive: 'PRODUCT_INACTIVE',
  numberUnavailable: 'ORDER_NUMBER_UNAVAILABLE',
} as const;

/**
 * A refused write names a condition the operator can act on, so each code gets
 * its own sentence instead of a generic «перевірте дані».
 */
export const ORDER_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  [ORDER_ERROR.notEditable]: 'Замовлення вже підтверджено — позиції не змінюються',
  [ORDER_ERROR.noItems]: 'Додайте хоча б одну позицію',
  [ORDER_ERROR.itemDuplicate]: 'Цей товар уже є в замовленні, змініть кількість',
  [ORDER_ERROR.currencyMismatch]: 'Валюту не можна змінити, поки в замовленні є позиції',
  [ORDER_ERROR.invalidTransition]: 'Такий перехід статусу недоступний',
  [ORDER_ERROR.insufficientStock]: 'Недостатньо залишку для підтвердження',
  [ORDER_ERROR.productInactive]: 'Товар вимкнено — його не можна додати до замовлення',
  [ORDER_ERROR.numberUnavailable]: 'Не вдалося виділити номер замовлення, спробуйте ще раз',
};

/** Every 409 whose code names a rule of the domain rather than a lost race. */
const ORDER_REFUSALS: ReadonlySet<string> = new Set(Object.keys(ORDER_ERROR_MESSAGES));

/**
 * A 409 carries two different answers. `ORDER_CONCURRENT_MODIFICATION` means
 * someone saved first, and re-reading the order fixes it. `INSUFFICIENT_STOCK`
 * or `ORDER_NOT_EDITABLE` mean the domain refused the request itself: the record
 * on screen is current, and offering a re-read sends the operator to do
 * something that cannot help. An unfamiliar code keeps the re-read, since a
 * stale version is the likelier of the two.
 */
export const isOrderVersionConflict = (error: unknown): boolean =>
  error instanceof ApiError && error.isConflict && !ORDER_REFUSALS.has(error.code);

/**
 * A line as the tables render it. The staged lines of an unsaved order and the
 * saved ones the API returns differ in origin, not in what has to be shown.
 */
export interface OrderItemView {
  readonly id: string;
  readonly productId: Id;
  readonly sku: string;
  readonly name: string;
  readonly quantity: number;
  readonly unitPrice: MoneyWire;
  readonly lineTotal: MoneyWire;
}
