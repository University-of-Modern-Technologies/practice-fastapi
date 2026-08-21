'use client';

import { Avatar, Button, Dropdown, Layout, Menu, Tooltip, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { LogOut, Moon, PanelLeft, Sun } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useMemo, type ReactNode } from 'react';
import { useLogout } from '@/shared/auth';
import { permissionScope, useAuthStore, useUiStore } from '@/shared/stores';
import { SURFACE } from '@/shared/constants';
import { useAppTheme } from '../hooks/use-app-theme';
import {
  NAVIGATION,
  navigationLinks,
  visibleNavigation,
  type NavigationLink,
  type NavigationNode,
} from './navigation';

/** Longest matching href wins, so /warehouse/movements does not light up /warehouse. */
const activeKey = (pathname: string, links: readonly NavigationLink[]): string | undefined =>
  links
    .filter((link) => pathname === link.href || pathname.startsWith(`${link.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.key;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const { appearance, toggle: toggleTheme } = useAppTheme();
  const logout = useLogout();

  const visible = useMemo(
    () =>
      visibleNavigation(
        NAVIGATION,
        (node) => !node.permission || permissionScope(user, ...node.permission) !== null,
      ),
    [user],
  );

  // The outermost level is drawn as headings rather than as collapsible
  // sections, which is why only it carries `type: 'group'`; everything below
  // is a link or a submenu and needs no special case.
  const toMenuItem = (node: NavigationNode): NonNullable<MenuProps['items']>[number] => ({
    key: node.key,
    ...(node.icon ? { icon: <node.icon size={16} /> } : {}),
    label: node.href ? <Link href={node.href}>{node.label}</Link> : node.label,
    ...(node.children ? { children: node.children.map(toMenuItem) } : {}),
  });

  const menuItems: MenuProps['items'] = visible.map((group) => ({
    ...toMenuItem(group),
    type: 'group',
  }));

  const links = navigationLinks(visible);
  const selectedKey = activeKey(pathname, links);
  // A submenu stays open while one of its own pages is showing, so the user
  // can see where they are without reopening the section on every navigation.
  const openKeys = visible
    .flatMap((group) => group.children ?? [])
    .filter((node) => navigationLinks(node.children ?? []).some((link) => link.key === selectedKey))
    .map((node) => node.key);

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={toggleSidebar}
        trigger={null}
        width={240}
        theme="light"
        style={{ borderInlineEnd: `1px solid ${SURFACE[appearance].border}` }}
      >
        <div className="flex h-14 items-center gap-2 px-4">
          <span
            className="grid size-8 shrink-0 place-items-center rounded-lg font-semibold text-white"
            style={{ background: 'var(--crm-color-primary)' }}
          >
            C
          </span>
          {collapsed ? null : (
            <Typography.Text strong className="truncate">
              CRM
            </Typography.Text>
          )}
        </div>
        <Menu
          mode="inline"
          items={menuItems}
          {...(selectedKey ? { selectedKeys: [selectedKey] } : {})}
          defaultOpenKeys={openKeys}
          style={{ borderInlineEnd: 'none' }}
        />
      </Layout.Sider>

      <Layout>
        <Layout.Header
          className="flex items-center justify-between gap-3 px-4"
          style={{
            background: SURFACE[appearance].container,
            borderBlockEnd: `1px solid ${SURFACE[appearance].border}`,
            height: 56,
            lineHeight: '56px',
          }}
        >
          <Button
            type="text"
            aria-label={collapsed ? 'Розгорнути меню' : 'Згорнути меню'}
            icon={<PanelLeft size={18} />}
            onClick={toggleSidebar}
          />

          <div className="flex items-center gap-2">
            <Tooltip title={appearance === 'dark' ? 'Світла тема' : 'Темна тема'}>
              <Button
                type="text"
                aria-label="Перемкнути тему"
                icon={appearance === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
                onClick={toggleTheme}
              />
            </Tooltip>

            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  {
                    key: 'logout',
                    icon: <LogOut size={16} />,
                    label: 'Вийти',
                    danger: true,
                    onClick: () => logout.mutate(),
                  },
                ],
              }}
            >
              {/* The visible text is the user's name, which is neither stable
                  nor present on a narrow screen; the label keeps the control
                  findable either way. */}
              <button
                type="button"
                aria-label="Обліковий запис"
                className="flex items-center gap-2"
              >
                <Avatar size={32} style={{ background: 'var(--crm-color-primary)' }}>
                  {user?.name?.charAt(0).toUpperCase() ?? '?'}
                </Avatar>
                <span className="hidden text-sm sm:inline">{user?.name}</span>
              </button>
            </Dropdown>
          </div>
        </Layout.Header>

        <Layout.Content className="p-4">{children}</Layout.Content>
      </Layout>
    </Layout>
  );
}
