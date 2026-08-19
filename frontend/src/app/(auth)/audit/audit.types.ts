import type { Id, IsoDateTime } from '@/types/domain';

export type AuditJsonPrimitive = string | number | boolean | null;
export type AuditJsonValue =
  AuditJsonPrimitive | readonly AuditJsonValue[] | { readonly [key: string]: AuditJsonValue };

export interface AuditRecord {
  readonly id: Id;
  readonly actorId: Id | null;
  readonly action: string;
  readonly entityType: string;
  readonly entityId: Id | null;
  readonly changes: AuditJsonValue | null;
  readonly metadata: AuditJsonValue | null;
  readonly ipAddress: string | null;
  readonly createdAt: IsoDateTime;
}

export interface AuditListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly actorId?: string;
  readonly action?: string;
  readonly entityType?: string;
  readonly entityId?: string;
  /** ISO 8601 instant with an offset — the API rejects a bare calendar date. */
  readonly createdFrom?: string;
  readonly createdTo?: string;
}

/** The record is already fixed by the path, so it carries no entity filters. */
export type AuditHistoryQuery = Omit<AuditListQuery, 'actorId' | 'entityType' | 'entityId'>;

/**
 * The entity names the API writes into the log, with the route that shows the
 * record itself. A name absent from here is still listed — it just has nothing
 * to link to.
 */
export const AUDIT_ENTITY: Readonly<
  Record<string, { readonly label: string; readonly route: ((id: string) => string) | null }>
> = {
  contact: { label: 'Контакт', route: (id) => `/contacts/${id}` },
  deal: { label: 'Угода', route: (id) => `/deals/${id}` },
  order: { label: 'Замовлення', route: (id) => `/orders/${id}` },
  product: { label: 'Товар', route: (id) => `/products/${id}` },
  warehouse: { label: 'Склад', route: (id) => `/warehouse/${id}` },
  stock: { label: 'Залишок', route: null },
  organization_setting: { label: 'Налаштування', route: null },
};

export const AUDIT_ENTITY_TYPES: readonly string[] = Object.keys(AUDIT_ENTITY);

export const auditEntityLabel = (entityType: string): string =>
  AUDIT_ENTITY[entityType]?.label ?? entityType;

export const auditEntityRoute = (entityType: string, entityId: string | null): string | null => {
  if (!entityId) return null;
  return AUDIT_ENTITY[entityType]?.route?.(entityId) ?? null;
};

/** Actions the modules record. Anything else is shown as the API spelled it. */
const AUDIT_ACTION_LABEL: Readonly<Record<string, string>> = {
  created: 'Створено',
  updated: 'Змінено',
  deleted: 'Видалено',
  stage_transitioned: 'Зміна стадії',
  status_transitioned: 'Зміна статусу',
  item_added: 'Додано позицію',
  item_updated: 'Змінено позицію',
  item_removed: 'Видалено позицію',
  reserved: 'Зарезервовано',
  released: 'Знято резерв',
};

/** `"deal.stage_transitioned"` → `"Зміна стадії"`, `"login"` → `"login"`. */
export const auditActionLabel = (action: string): string => {
  const verb = action.includes('.') ? action.slice(action.indexOf('.') + 1) : action;
  return AUDIT_ACTION_LABEL[verb] ?? action;
};
