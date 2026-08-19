import { Suspense, type ReactNode } from 'react';
import { RouteGuard, TablePageSkeleton } from '@/components';
import { AppShell } from '@/templates/layouts';

/** Everything under this group requires a session. */
export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard>
      <AppShell>
        {/*
          List pages read their state out of the query string, and that suspends
          while the route is being prepared. Holding the boundary here means no
          module has to remember to add one of its own.
        */}
        <Suspense fallback={<TablePageSkeleton />}>{children}</Suspense>
      </AppShell>
    </RouteGuard>
  );
}
