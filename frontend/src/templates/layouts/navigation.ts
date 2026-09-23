import {
  Boxes,
  ChartColumn,
  ClipboardList,
  Contact,
  Headset,
  Handshake,
  Layers,
  Landmark,
  LayoutDashboard,
  Package,
  PhoneCall,
  Plug,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  Warehouse,
  type LucideIcon,
} from 'lucide-react';

/**
 * One entry in the sidebar. A node either leads somewhere or gathers others,
 * and the shell treats both the same way — which is what lets a section grow a
 * level without the rendering, the filtering or the active-item lookup having
 * to learn about it.
 */
export interface NavigationNode {
  readonly key: string;
  readonly label: string;
  /** Absent on a node that only gathers others. */
  readonly href?: string;
  /** Absent on the outermost nodes, which antd renders as plain headings. */
  readonly icon?: LucideIcon;
  /**
   * The `resource:action` pair the node needs. Absent means always visible.
   * Hiding is courtesy only — the API refuses the call either way.
   */
  readonly permission?: readonly [resource: string, action: string];
  readonly children?: readonly NavigationNode[];
}

/** A node the user can actually go to. */
export type NavigationLink = NavigationNode & { readonly href: string };

export const isNavigationLink = (node: NavigationNode): node is NavigationLink =>
  node.href !== undefined;

/** Every reachable destination in the tree, in the order it is drawn. */
export const navigationLinks = (nodes: readonly NavigationNode[]): readonly NavigationLink[] =>
  nodes.flatMap((node) => [
    ...(isNavigationLink(node) ? [node] : []),
    ...navigationLinks(node.children ?? []),
  ]);

/**
 * Drops what the caller may not see, at every depth.
 *
 * A child inherits its parent's requirement rather than restating it, so the
 * test has to be applied on the way down: the warehouse screens carry no
 * permission of their own, and reading them out of a flattened list would
 * offer stock levels to someone the API will refuse.
 *
 * A node that gathers others and has nothing left to gather goes with them —
 * an empty heading, or a section that opens onto nothing, reads as a broken
 * page rather than as an absent permission.
 */
export const visibleNavigation = (
  nodes: readonly NavigationNode[],
  allows: (node: NavigationNode) => boolean,
): readonly NavigationNode[] =>
  nodes
    .filter(allows)
    .map((node) =>
      node.children ? { ...node, children: visibleNavigation(node.children, allows) } : node,
    )
    .filter((node) => node.href !== undefined || (node.children?.length ?? 0) > 0);

export const NAVIGATION: readonly NavigationNode[] = [
  {
    key: 'overview',
    label: 'Огляд',
    children: [
      { key: 'dashboard', label: 'Дашборд', href: '/', icon: LayoutDashboard },
      {
        key: 'analytics',
        label: 'Аналітика',
        href: '/analytics',
        icon: ChartColumn,
        permission: ['analytics', 'read'],
      },
    ],
  },
  {
    key: 'sales',
    label: 'Продажі',
    children: [
      {
        key: 'contacts',
        label: 'Контакти',
        href: '/contacts',
        icon: Contact,
        permission: ['contacts', 'read'],
      },
      {
        key: 'deals',
        label: 'Угоди',
        href: '/deals',
        icon: Handshake,
        permission: ['deals', 'read'],
      },
      {
        key: 'orders',
        label: 'Замовлення',
        href: '/orders',
        icon: ClipboardList,
        permission: ['orders', 'read'],
      },
      {
        key: 'finance',
        label: 'Фінанси',
        href: '/finance',
        icon: Landmark,
        permission: ['finance', 'read'],
      },
    ],
  },
  {
    key: 'service',
    label: 'Обслуговування',
    children: [
      {
        key: 'helpdesk',
        label: 'Звернення',
        href: '/helpdesk',
        icon: Headset,
        permission: ['helpdesk', 'read'],
      },
      {
        key: 'calls',
        label: 'Дзвінки',
        href: '/calls',
        icon: PhoneCall,
        permission: ['calls', 'read'],
      },
    ],
  },
  {
    key: 'stock',
    label: 'Товари і склад',
    children: [
      {
        key: 'products',
        label: 'Товари',
        href: '/products',
        icon: Package,
        permission: ['products', 'read'],
      },
      {
        // Three screens read the same resource from different angles, which is
        // one more than fits a flat list without crowding out the rest of the
        // section — stock levels had no entry at all until they gained a level
        // of their own.
        key: 'warehouse',
        label: 'Склад',
        icon: Warehouse,
        permission: ['warehouse', 'read'],
        children: [
          { key: 'warehouses', label: 'Склади', href: '/warehouse', icon: Warehouse },
          { key: 'stock', label: 'Залишки', href: '/warehouse/stock', icon: Layers },
          { key: 'movements', label: 'Рухи товару', href: '/warehouse/movements', icon: Boxes },
        ],
      },
    ],
  },
  {
    key: 'administration',
    label: 'Адміністрування',
    children: [
      {
        key: 'users',
        label: 'Користувачі',
        href: '/users',
        icon: Users,
        permission: ['users', 'read'],
      },
      {
        key: 'roles',
        label: 'Доступи',
        href: '/roles',
        icon: ShieldCheck,
        // Role administration has no permission of its own: the API guards the
        // `/rbac/roles` endpoints with the `users` ones, so whoever may edit
        // accounts is exactly whoever may decide what those accounts can do.
        permission: ['users', 'read'],
      },
      {
        key: 'settings',
        label: 'Налаштування',
        href: '/settings',
        icon: Settings,
        permission: ['settings', 'read'],
      },
      {
        key: 'audit',
        label: 'Аудит',
        href: '/audit',
        icon: ScrollText,
        permission: ['audit', 'read'],
      },
    ],
  },
  {
    key: 'external',
    label: 'Зовнішні системи',
    children: [
      {
        key: 'integrations',
        label: 'Інтеграції',
        href: '/integrations',
        icon: Plug,
        permission: ['integrations', 'read'],
      },
      { key: 'ai', label: 'AI-помічник', href: '/ai', icon: Sparkles, permission: ['ai', 'use'] },
    ],
  },
];
