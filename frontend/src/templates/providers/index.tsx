'use client';

import { AntdRegistry } from '@ant-design/nextjs-registry';
import type { ReactNode } from 'react';
import { AntdProvider } from './antd-provider';
import { QueryProvider } from './query-provider';
import { RealtimeProvider } from './realtime-provider';
import { SessionProvider } from './session-provider';
import { ThemeProvider } from './theme-provider';

/**
 * Order matters: the theme has to be known before the component library reads
 * it, and the session has to be restored inside the query cache so a renewal
 * can invalidate what it needs.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AntdRegistry>
      <ThemeProvider>
        <QueryProvider>
          <AntdProvider>
            <SessionProvider>
              <RealtimeProvider>{children}</RealtimeProvider>
            </SessionProvider>
          </AntdProvider>
        </QueryProvider>
      </ThemeProvider>
    </AntdRegistry>
  );
}

export { AntdProvider, QueryProvider, RealtimeProvider, SessionProvider, ThemeProvider };
