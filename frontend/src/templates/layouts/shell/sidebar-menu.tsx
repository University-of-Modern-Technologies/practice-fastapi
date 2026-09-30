'use client';

import { Menu } from 'antd';
import type { MenuProps } from 'antd';
import Link from 'next/link';
import { navigationLinks, type NavigationNode } from '../navigation';
import { useShellNavigation } from './use-shell-navigation';

type MenuItem = NonNullable<MenuProps['items']>[number];

const toMenuItem = (node: NavigationNode): MenuItem => ({
  key: node.key,
  ...(node.icon ? { icon: <node.icon size={17} strokeWidth={1.75} /> } : {}),
  label: node.href ? <Link href={node.href}>{node.label}</Link> : node.label,
  ...(node.children ? { children: node.children.map(toMenuItem) } : {}),
});

interface SidebarMenuProps {
  /** Icons only: headings give way to dividers, which still separate the sections. */
  readonly collapsed?: boolean;
  /** Called after a page is chosen, so a drawer can close itself. */
  readonly onNavigate?: () => void;
}

export function SidebarMenu({ collapsed = false, onNavigate }: SidebarMenuProps) {
  const { visible, selectedKey } = useShellNavigation();

  // The outermost level is drawn as headings rather than as collapsible
  // sections; everything below is a link or a submenu and needs no special case.
  const items: MenuProps['items'] = collapsed
    ? visible.flatMap((group, index) => [
        ...(index > 0 ? [{ type: 'divider' as const, key: `${group.key}-divider` }] : []),
        ...(group.children ?? []).map(toMenuItem),
      ])
    : visible.map((group) => ({ ...toMenuItem(group), type: 'group' as const }));

  // A submenu stays open while one of its own pages is showing, so the user
  // can see where they are without reopening the section on every navigation.
  const openKeys = visible
    .flatMap((group) => group.children ?? [])
    .filter((node) => navigationLinks(node.children ?? []).some((link) => link.key === selectedKey))
    .map((node) => node.key);

  return (
    <Menu
      mode="inline"
      // Inside a Sider the menu takes its collapsed state from it; `collapsed`
      // here only reshapes the items.
      items={items}
      {...(selectedKey ? { selectedKeys: [selectedKey] } : {})}
      defaultOpenKeys={openKeys}
      {...(onNavigate ? { onClick: onNavigate } : {})}
      style={{ borderInlineEnd: 'none', background: 'transparent' }}
    />
  );
}
