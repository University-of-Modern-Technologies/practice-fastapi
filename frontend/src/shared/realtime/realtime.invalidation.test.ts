import { describe, expect, it } from 'vitest';
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
import { invalidationKeysFor } from './realtime.invalidation';
import type { RealtimeDomainEvent } from './realtime.types';

const event = (
  eventType: string,
  entityType: string,
  entityId: string,
  payload: unknown = null,
): RealtimeDomainEvent => ({ eventType, entityType, entityId, actorId: 'u-1', payload });

const keysOf = (input: RealtimeDomainEvent): unknown[][] =>
  invalidationKeysFor(input).map((key) => [...key]);

describe('invalidationKeysFor', () => {
  const cases: readonly {
    readonly name: string;
    readonly event: RealtimeDomainEvent;
    readonly expected: readonly unknown[][];
  }[] = [
    {
      name: 'deal.created refreshes the lists only',
      event: event('deal.created', 'deal', 'd-1'),
      expected: [[...dealsKeys.lists()]],
    },
    {
      name: 'deal.updated refreshes that card and the lists',
      event: event('deal.updated', 'deal', 'd-1'),
      expected: [[...dealsKeys.detail('d-1')], [...dealsKeys.lists()]],
    },
    {
      name: 'deal.stage_transitioned refreshes that card and the lists',
      event: event('deal.stage_transitioned', 'deal', 'd-2'),
      expected: [[...dealsKeys.detail('d-2')], [...dealsKeys.lists()]],
    },
    {
      name: 'order.updated stays inside orders',
      event: event('order.updated', 'order', 'o-1'),
      expected: [[...ordersKeys.detail('o-1')], [...ordersKeys.lists()]],
    },
    {
      name: 'order.status_transitioned reaches the warehouse too',
      event: event('order.status_transitioned', 'order', 'o-1'),
      expected: [
        [...ordersKeys.detail('o-1')],
        [...ordersKeys.lists()],
        [...stockKeys.lists()],
        [...movementsKeys.lists()],
      ],
    },
    {
      name: 'contact.updated refreshes that card and the lists',
      event: event('contact.updated', 'contact', 'c-1'),
      expected: [[...contactsKeys.detail('c-1')], [...contactsKeys.lists()]],
    },
    {
      name: 'product.updated refreshes that card and the lists',
      event: event('product.updated', 'product', 'p-1'),
      expected: [[...productsKeys.detail('p-1')], [...productsKeys.lists()]],
    },
    {
      name: 'user.updated refreshes that card and the lists',
      event: event('user.updated', 'user', 'u-9'),
      expected: [[...usersKeys.detail('u-9')], [...usersKeys.lists()]],
    },
    {
      name: 'stock.reserved refreshes levels and the ledger',
      event: event('stock.reserved', 'stock', 's-1'),
      expected: [[...stockKeys.lists()], [...movementsKeys.lists()]],
    },
    {
      name: 'stock.reserved also addresses the open card when the pair is named',
      event: event('stock.reserved', 'stock', 's-1', { warehouseId: 'w-1', productId: 'p-1' }),
      expected: [
        [...stockKeys.lists()],
        [...movementsKeys.lists()],
        [...stockKeys.detail('w-1', 'p-1')],
      ],
    },
    {
      name: 'warehouse.created refreshes the lists only',
      event: event('warehouse.created', 'warehouse', 'w-1'),
      expected: [[...warehousesKeys.lists()]],
    },
    {
      name: 'warehouse.updated refreshes that card and the lists',
      event: event('warehouse.updated', 'warehouse', 'w-1'),
      expected: [[...warehousesKeys.detail('w-1')], [...warehousesKeys.lists()]],
    },
    {
      name: 'setting.updated drops the settings branch',
      event: event('setting.updated', 'setting', 'currency'),
      expected: [[...settingsKeys.all]],
    },
  ];

  it.each(cases)('$name', ({ event: input, expected }) => {
    // The audit log records every change, so it trails every mapped event.
    expect(keysOf(input)).toEqual([...expected, [...auditKeys.lists()]]);
  });

  it('returns nothing for an event type this build does not know', () => {
    expect(invalidationKeysFor(event('shipment.dispatched', 'shipment', 's-1'))).toEqual([]);
  });

  it('never invalidates a whole module root except settings', () => {
    const roots = new Set(['deals', 'orders', 'contacts', 'products', 'users', 'stock']);

    for (const { event: input } of cases) {
      for (const key of invalidationKeysFor(input)) {
        expect(key.length === 1 && roots.has(String(key[0]))).toBe(false);
      }
    }
  });

  it('reports each key once', () => {
    const keys = invalidationKeysFor(event('order.status_transitioned', 'order', 'o-1'));
    const markers = keys.map((key) => JSON.stringify(key));

    expect(new Set(markers).size).toBe(markers.length);
  });
});
