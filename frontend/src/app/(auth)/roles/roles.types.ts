import type { PermissionGrant, PermissionScope } from '@/shared/api';
import type { Id, Timestamps } from '@/types/domain';

export type { PermissionGrant, PermissionScope };

export interface Role extends Timestamps {
  readonly id: Id;
  readonly name: string;
  readonly description: string | null;
  readonly permissions: readonly PermissionGrant[];
}

export interface CreateRoleInput {
  readonly name: string;
  readonly description?: string;
  readonly permissions: readonly PermissionGrant[];
}

/** Answer of `GET /rbac/check/:resource/:action` for the current caller. */
export interface PermissionCheck {
  readonly allowed: boolean;
  readonly scope: PermissionScope | null;
}

export interface RoleFormValues {
  readonly name: string;
  readonly description?: string;
}

/**
 * The permissions the API knows about. A pair outside this list is answered
 * with 400 `UNKNOWN_PERMISSION`, so the matrix offers a cell only where a real
 * permission exists rather than every resource-action combination.
 */
export const PERMISSION_CATALOGUE: readonly (readonly [resource: string, action: string])[] = [
  ['users', 'read'],
  ['users', 'create'],
  ['users', 'update'],
  ['users', 'disable'],
  ['contacts', 'read'],
  ['contacts', 'write'],
  ['contacts', 'delete'],
  ['deals', 'read'],
  ['deals', 'write'],
  ['deals', 'delete'],
  ['products', 'read'],
  ['products', 'write'],
  ['products', 'delete'],
  ['orders', 'read'],
  ['orders', 'write'],
  ['orders', 'delete'],
  ['warehouse', 'read'],
  ['warehouse', 'write'],
  ['settings', 'read'],
  ['settings', 'write'],
  ['audit', 'read'],
  ['analytics', 'read'],
  ['integrations', 'read'],
  ['integrations', 'write'],
  ['ai', 'use'],
];

export const PERMISSION_RESOURCE_LABEL: Readonly<Record<string, string>> = {
  users: 'Користувачі',
  contacts: 'Контакти',
  deals: 'Угоди',
  products: 'Товари',
  orders: 'Замовлення',
  warehouse: 'Склад',
  settings: 'Налаштування',
  audit: 'Аудит',
  analytics: 'Аналітика',
  integrations: 'Інтеграції',
  ai: 'AI-помічник',
};

export const PERMISSION_ACTION_LABEL: Readonly<Record<string, string>> = {
  read: 'Перегляд',
  create: 'Створення',
  update: 'Редагування',
  write: 'Запис',
  delete: 'Видалення',
  disable: 'Вимкнення',
  use: 'Використання',
};

/** Resources in the order the matrix shows them, derived from the catalogue. */
export const PERMISSION_RESOURCES: readonly string[] = [
  ...new Set(PERMISSION_CATALOGUE.map(([resource]) => resource)),
];

export const PERMISSION_ACTIONS: readonly string[] = [
  ...new Set(PERMISSION_CATALOGUE.map(([, action]) => action)),
];

export const permissionKey = (resource: string, action: string): string => `${resource}:${action}`;

const CATALOGUE_KEYS = new Set(
  PERMISSION_CATALOGUE.map(([resource, action]) => permissionKey(resource, action)),
);

export const isKnownPermission = (resource: string, action: string): boolean =>
  CATALOGUE_KEYS.has(permissionKey(resource, action));
