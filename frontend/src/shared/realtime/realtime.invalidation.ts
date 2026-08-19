import { auditKeys } from '@/app/(auth)/audit/audit.queries';
import { contactsKeys } from '@/app/(auth)/contacts/contacts.queries';
import { dealsKeys } from '@/app/(auth)/deals/deals.queries';
import { ordersKeys } from '@/app/(auth)/orders/orders.queries';
import { productsKeys } from '@/app/(auth)/products/products.queries';
import { settingsKeys } from '@/app/(auth)/settings/settings.queries';
import { usersKeys } from '@/app/(auth)/users/users.queries';
import { movementsKeys } from '@/app/(auth)/warehouse/movements.queries';
import { stockKeys } from '@/app/(auth)/warehouse/stock.queries';
import { warehousesKeys } from '@/app/(auth)/warehouse/warehouse.queries';
import type { RealtimeDomainEvent } from './realtime.types';

/**
 * Maps a domain event onto the exact cache entries it invalidates.
 *
 * The key factories are the modules' own — read here, never redefined. The
 * whole point of the channel is that a change refreshes what it touched:
 * `queryClient.clear()` and blanket invalidation are what this file exists to
 * avoid, because they would restart every open table on every event.
 */

export type InvalidationKey = readonly unknown[];

/** Reads an id out of the event payload without trusting its shape. */
const readId = (payload: unknown, field: string): string | null => {
  if (typeof payload !== 'object' || payload === null) return null;
  const value = (payload as Record<string, unknown>)[field];
  return typeof value === 'string' && value !== '' ? value : null;
};

const dealKeys = (id: string): readonly InvalidationKey[] => [
  dealsKeys.detail(id),
  dealsKeys.lists(),
];

const orderKeys = (id: string): readonly InvalidationKey[] => [
  ordersKeys.detail(id),
  ordersKeys.lists(),
];

/** A confirmed or cancelled order moves stock, so the ledger moves with it. */
const orderWithStockKeys = (id: string): readonly InvalidationKey[] => [
  ...orderKeys(id),
  stockKeys.lists(),
  movementsKeys.lists(),
];

const stockLevelKeys = (event: RealtimeDomainEvent): readonly InvalidationKey[] => {
  const warehouseId = readId(event.payload, 'warehouseId');
  const productId = readId(event.payload, 'productId');

  return [
    stockKeys.lists(),
    movementsKeys.lists(),
    // An open stock card is addressed directly when the event names the pair.
    ...(warehouseId && productId ? [stockKeys.detail(warehouseId, productId)] : []),
  ];
};

type EventKeyResolver = (event: RealtimeDomainEvent) => readonly InvalidationKey[];

const RESOLVERS: Readonly<Record<string, EventKeyResolver>> = {
  'deal.created': () => [dealsKeys.lists()],
  'deal.updated': (event) => dealKeys(event.entityId),
  'deal.stage_transitioned': (event) => dealKeys(event.entityId),
  'deal.deleted': (event) => dealKeys(event.entityId),

  'order.created': () => [ordersKeys.lists()],
  'order.updated': (event) => orderKeys(event.entityId),
  'order.item_added': (event) => orderKeys(event.entityId),
  'order.item_updated': (event) => orderKeys(event.entityId),
  'order.item_removed': (event) => orderKeys(event.entityId),
  'order.status_transitioned': (event) => orderWithStockKeys(event.entityId),
  'order.deleted': (event) => orderWithStockKeys(event.entityId),

  'contact.created': () => [contactsKeys.lists()],
  'contact.updated': (event) => [contactsKeys.detail(event.entityId), contactsKeys.lists()],
  'contact.deleted': (event) => [contactsKeys.detail(event.entityId), contactsKeys.lists()],

  'product.created': () => [productsKeys.lists()],
  'product.updated': (event) => [productsKeys.detail(event.entityId), productsKeys.lists()],
  'product.deleted': (event) => [productsKeys.detail(event.entityId), productsKeys.lists()],

  'user.created': () => [usersKeys.lists()],
  'user.updated': (event) => [usersKeys.detail(event.entityId), usersKeys.lists()],
  'user.disabled': (event) => [usersKeys.detail(event.entityId), usersKeys.lists()],
  'user.deleted': (event) => [usersKeys.detail(event.entityId), usersKeys.lists()],

  'stock.received': stockLevelKeys,
  'stock.issued': stockLevelKeys,
  'stock.reserved': stockLevelKeys,
  'stock.released': stockLevelKeys,
  'stock.adjusted': stockLevelKeys,

  'warehouse.created': () => [warehousesKeys.lists()],
  'warehouse.updated': (event) => [warehousesKeys.detail(event.entityId), warehousesKeys.lists()],
  'warehouse.deleted': (event) => [warehousesKeys.detail(event.entityId), warehousesKeys.lists()],

  // Other modules read settings through their own calls, so the branch goes as
  // a whole — the same choice the settings module makes after its own write.
  'setting.updated': () => [settingsKeys.all],
  'setting.deleted': () => [settingsKeys.all],
};

const dropDuplicates = (keys: readonly InvalidationKey[]): readonly InvalidationKey[] => {
  const seen = new Set<string>();
  return keys.filter((key) => {
    const marker = JSON.stringify(key);
    if (seen.has(marker)) return false;
    seen.add(marker);
    return true;
  });
};

/**
 * Returns the query keys a single event makes stale. An event type this build
 * does not know yields an empty list — a newer API may publish more than this
 * client understands, and guessing would mean refetching at random.
 */
export const invalidationKeysFor = (event: RealtimeDomainEvent): readonly InvalidationKey[] => {
  const resolve = RESOLVERS[event.eventType];
  if (!resolve) return [];

  // Every domain event also appends an audit record, so an open log is one of
  // the views the event genuinely invalidates.
  return dropDuplicates([...resolve(event), auditKeys.lists()]);
};
