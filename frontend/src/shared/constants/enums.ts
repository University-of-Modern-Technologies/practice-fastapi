/**
 * The single place where a value from the API gets a Ukrainian label and a
 * colour. Nothing else in the client is allowed to spell out `'QUALIFIED'` in a
 * user-facing string: when the backend adds a state, this file is the only edit.
 */

/** Ant Design preset tag colours; anything else drifts from the palette. */
export type StatusColor = 'default' | 'processing' | 'success' | 'warning' | 'error';

export interface StatusMeta {
  readonly label: string;
  readonly color: StatusColor;
}

export const DEAL_STAGES = ['LEAD', 'QUALIFIED', 'PROPOSAL', 'WON', 'LOST'] as const;
export type DealStage = (typeof DEAL_STAGES)[number];

export const DEAL_STAGE: Readonly<Record<DealStage, StatusMeta>> = {
  LEAD: { label: 'Лід', color: 'default' },
  QUALIFIED: { label: 'Кваліфіковано', color: 'processing' },
  PROPOSAL: { label: 'Пропозиція', color: 'warning' },
  WON: { label: 'Виграно', color: 'success' },
  LOST: { label: 'Втрачено', color: 'error' },
};

/**
 * Mirrors the state machine the API enforces. The UI offers only the moves
 * listed here, so an impossible transition is never proposed — the 409 the
 * server would answer with stays a safety net rather than the primary check.
 */
export const DEAL_STAGE_TRANSITIONS: Readonly<Record<DealStage, readonly DealStage[]>> = {
  LEAD: ['QUALIFIED'],
  QUALIFIED: ['PROPOSAL'],
  PROPOSAL: ['WON', 'LOST'],
  WON: [],
  LOST: [],
};

export const TICKET_CHANNELS = ['EMAIL', 'PHONE', 'CHAT', 'WEB'] as const;
export type TicketChannel = (typeof TICKET_CHANNELS)[number];

export const TICKET_STATUSES = ['NEW', 'OPEN', 'PENDING', 'RESOLVED', 'CLOSED'] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

export const TICKET_PRIORITIES = ['LOW', 'NORMAL', 'HIGH', 'URGENT'] as const;
export type TicketPriority = (typeof TICKET_PRIORITIES)[number];

export const TICKET_CHANNEL: Readonly<Record<TicketChannel, StatusMeta>> = {
  EMAIL: { label: 'Пошта', color: 'default' },
  PHONE: { label: 'Телефон', color: 'processing' },
  CHAT: { label: 'Чат', color: 'warning' },
  WEB: { label: 'Вебформа', color: 'default' },
};

export const TICKET_STATUS: Readonly<Record<TicketStatus, StatusMeta>> = {
  NEW: { label: 'Нове', color: 'default' },
  OPEN: { label: 'У роботі', color: 'processing' },
  PENDING: { label: 'Очікує відповіді', color: 'warning' },
  RESOLVED: { label: 'Розвʼязано', color: 'success' },
  CLOSED: { label: 'Закрито', color: 'default' },
};

export const TICKET_PRIORITY: Readonly<Record<TicketPriority, StatusMeta>> = {
  LOW: { label: 'Низький', color: 'default' },
  NORMAL: { label: 'Звичайний', color: 'processing' },
  HIGH: { label: 'Високий', color: 'warning' },
  URGENT: { label: 'Терміновий', color: 'error' },
};

/**
 * Mirrors the state machine the API enforces. The card offers only the moves
 * listed here, so a step the server would refuse is never proposed — its 422
 * stays a safety net rather than the first check.
 */
export const TICKET_STATUS_TRANSITIONS: Readonly<Record<TicketStatus, readonly TicketStatus[]>> = {
  NEW: ['OPEN', 'CLOSED'],
  OPEN: ['PENDING', 'RESOLVED', 'CLOSED'],
  PENDING: ['OPEN', 'RESOLVED', 'CLOSED'],
  // Reopening is a published move: a ticket the customer came back about goes
  // from `RESOLVED` to `OPEN`, and the server clears `resolvedAt` with it.
  RESOLVED: ['CLOSED', 'OPEN'],
  CLOSED: [],
};

export const CALL_DIRECTIONS = ['INBOUND', 'OUTBOUND'] as const;
export type CallDirection = (typeof CALL_DIRECTIONS)[number];

export const CALL_DISPOSITIONS = ['ANSWERED', 'NO_ANSWER', 'BUSY', 'FAILED', 'VOICEMAIL'] as const;
export type CallDisposition = (typeof CALL_DISPOSITIONS)[number];

export const CALL_DIRECTION: Readonly<Record<CallDirection, StatusMeta>> = {
  INBOUND: { label: 'Вхідний', color: 'processing' },
  OUTBOUND: { label: 'Вихідний', color: 'default' },
};

export const CALL_DISPOSITION: Readonly<Record<CallDisposition, StatusMeta>> = {
  ANSWERED: { label: 'Відповіли', color: 'success' },
  NO_ANSWER: { label: 'Без відповіді', color: 'warning' },
  BUSY: { label: 'Зайнято', color: 'warning' },
  FAILED: { label: 'Помилка звʼязку', color: 'error' },
  VOICEMAIL: { label: 'Голосова пошта', color: 'default' },
};

/** Probability the API demands for a terminal stage; null means it is free. */
export const DEAL_STAGE_PROBABILITY: Readonly<Record<DealStage, number | null>> = {
  LEAD: null,
  QUALIFIED: null,
  PROPOSAL: null,
  WON: 100,
  LOST: 0,
};

export const ORDER_STATUSES = ['DRAFT', 'CONFIRMED', 'PAID', 'FULFILLED', 'CANCELLED'] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export const ORDER_STATUS: Readonly<Record<OrderStatus, StatusMeta>> = {
  DRAFT: { label: 'Чернетка', color: 'default' },
  CONFIRMED: { label: 'Підтверджено', color: 'processing' },
  PAID: { label: 'Оплачено', color: 'warning' },
  FULFILLED: { label: 'Виконано', color: 'success' },
  CANCELLED: { label: 'Скасовано', color: 'error' },
};

export const ORDER_STATUS_TRANSITIONS: Readonly<Record<OrderStatus, readonly OrderStatus[]>> = {
  DRAFT: ['CONFIRMED', 'CANCELLED'],
  CONFIRMED: ['PAID', 'CANCELLED'],
  PAID: ['FULFILLED', 'CANCELLED'],
  FULFILLED: [],
  CANCELLED: [],
};

/** Items and money may only be edited while the order is still a draft. */
export const isOrderEditable = (status: OrderStatus): boolean => status === 'DRAFT';

export const STOCK_MOVEMENT_TYPES = [
  'RECEIPT',
  'ISSUE',
  'RESERVATION',
  'RELEASE',
  'ADJUSTMENT',
] as const;
export type StockMovementType = (typeof STOCK_MOVEMENT_TYPES)[number];

export const STOCK_MOVEMENT_TYPE: Readonly<Record<StockMovementType, StatusMeta>> = {
  RECEIPT: { label: 'Оприбуткування', color: 'success' },
  ISSUE: { label: 'Списання', color: 'error' },
  RESERVATION: { label: 'Резервування', color: 'processing' },
  RELEASE: { label: 'Зняття резерву', color: 'default' },
  ADJUSTMENT: { label: 'Коригування', color: 'warning' },
};

export const SHIPMENT_STATUSES = [
  'CREATED',
  'IN_TRANSIT',
  'DELIVERED',
  'CANCELLED',
  'FAILED',
] as const;
export type ShipmentStatus = (typeof SHIPMENT_STATUSES)[number];

export const SHIPMENT_STATUS: Readonly<Record<ShipmentStatus, StatusMeta>> = {
  CREATED: { label: 'Створено', color: 'default' },
  IN_TRANSIT: { label: 'У дорозі', color: 'processing' },
  DELIVERED: { label: 'Доставлено', color: 'success' },
  CANCELLED: { label: 'Скасовано', color: 'warning' },
  FAILED: { label: 'Помилка', color: 'error' },
};

/**
 * Closed list the classifier may answer with, plus the value the API returns
 * when the model invented something outside it.
 */
export const INQUIRY_CATEGORIES = [
  'billing',
  'sales',
  'technical_support',
  'shipping',
  'complaint',
  'other',
  'unknown',
] as const;
export type InquiryCategory = (typeof INQUIRY_CATEGORIES)[number];

export const INQUIRY_CATEGORY: Readonly<Record<InquiryCategory, StatusMeta>> = {
  billing: { label: 'Оплата', color: 'warning' },
  sales: { label: 'Продажі', color: 'processing' },
  technical_support: { label: 'Технічна підтримка', color: 'default' },
  shipping: { label: 'Доставка', color: 'default' },
  complaint: { label: 'Скарга', color: 'error' },
  other: { label: 'Інше', color: 'default' },
  unknown: { label: 'Не визначено', color: 'error' },
};

/** The breaker guards the outbound calls; the client only reads its state. */
export const CIRCUIT_STATES = ['closed', 'half-open', 'open'] as const;
export type CircuitState = (typeof CIRCUIT_STATES)[number];

export const CIRCUIT_STATE: Readonly<Record<CircuitState, StatusMeta>> = {
  closed: { label: 'Працює', color: 'success' },
  'half-open': { label: 'Перевірка', color: 'warning' },
  open: { label: 'Розімкнено', color: 'error' },
};

export const PERMISSION_SCOPES = ['ALL', 'OWN'] as const;
export type PermissionScopeValue = (typeof PERMISSION_SCOPES)[number];

export const PERMISSION_SCOPE: Readonly<Record<PermissionScopeValue, string>> = {
  ALL: 'Усі записи',
  OWN: 'Тільки свої',
};

/**
 * Reads a label out of a dictionary without assuming the value is known. A
 * state added on the server must show up as itself rather than as `undefined`.
 */
export const statusMeta = (
  dictionary: Readonly<Record<string, StatusMeta>>,
  value: string,
): StatusMeta => {
  // Own keys only: a plain lookup answers `'toString'` with a function off the
  // prototype, and the fallback would be skipped for a value it should catch.
  const known = Object.hasOwn(dictionary, value) ? dictionary[value] : undefined;
  return known ?? { label: value, color: 'default' };
};
