'use client';

import { Grid, Layout } from 'antd';
import { usePathname } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { useUiStore } from '@/shared/stores';
import { Header } from './shell/header';
import { DesktopSidebar, MobileSidebar } from './shell/sidebar';

/**
 * The frame around every signed-in page: a sidebar that stays in place, a
 * header that stays on top, and the page between them. Below the `lg`
 * breakpoint the sidebar becomes a drawer opened from the header.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const screens = Grid.useBreakpoint();
  const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen);
  // Unknown until the first measurement on the client; the server and the
  // first client render both assume a wide screen, so they agree.
  const mobile = screens.lg === false;

  useEffect(() => {
    void useUiStore.persist.rehydrate();
  }, []);

  // A drawer left open across a navigation would cover the page just opened.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname, setMobileNavOpen]);

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {mobile ? <MobileSidebar /> : <DesktopSidebar />}
      <Layout className="min-w-0">
        <Header mobile={mobile} />
        <Layout.Content className="p-4 md:p-6">
          {/* A table stretched across a wide monitor is harder to read, not easier. */}
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
