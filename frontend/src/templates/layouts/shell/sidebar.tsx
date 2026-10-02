'use client';

import { Drawer, Layout } from 'antd';
import Link from 'next/link';
import { useUiStore } from '@/shared/stores';
import { Brand } from './brand';
import { HEADER_HEIGHT } from './metrics';
import { SidebarMenu } from './sidebar-menu';

const SIDER_WIDTH = 248;
const SIDER_COLLAPSED_WIDTH = 72;

function BrandRow({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`flex shrink-0 items-center ${compact ? 'justify-center' : 'px-5'}`}
      style={{ height: HEADER_HEIGHT }}
    >
      <Link href="/" aria-label="На головну" className="min-w-0 text-inherit no-underline">
        <Brand compact={compact} />
      </Link>
    </div>
  );
}

/**
 * The fixed sidebar on a wide screen: it stays in place while the page
 * scrolls and scrolls on its own when the menu is longer than the window.
 */
export function DesktopSidebar() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);

  return (
    <Layout.Sider
      collapsible
      collapsed={collapsed}
      trigger={null}
      width={SIDER_WIDTH}
      collapsedWidth={SIDER_COLLAPSED_WIDTH}
      theme="light"
      style={{
        position: 'sticky',
        top: 0,
        height: '100vh',
        borderInlineEnd: '1px solid var(--crm-color-border-secondary)',
      }}
    >
      <div className="flex h-full flex-col">
        <BrandRow compact={collapsed} />
        <nav
          aria-label="Основна навігація"
          className="min-h-0 flex-1 [scrollbar-width:thin] [scrollbar-color:var(--crm-color-fill)_transparent] overflow-y-auto pb-4"
        >
          <SidebarMenu collapsed={collapsed} />
        </nav>
      </div>
    </Layout.Sider>
  );
}

/** The same menu on a narrow screen, pulled out from the left and closed by a choice. */
export function MobileSidebar() {
  const open = useUiStore((state) => state.mobileNavOpen);
  const setOpen = useUiStore((state) => state.setMobileNavOpen);

  return (
    <Drawer
      placement="left"
      open={open}
      onClose={() => setOpen(false)}
      closable={false}
      size={SIDER_WIDTH + 32}
      styles={{ body: { padding: 0 } }}
    >
      <BrandRow />
      <nav aria-label="Основна навігація" className="pb-4">
        <SidebarMenu onNavigate={() => setOpen(false)} />
      </nav>
    </Drawer>
  );
}
