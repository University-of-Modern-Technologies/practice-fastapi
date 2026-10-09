'use client';

import { Button, Result } from 'antd';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { resumeSession } from '@/shared/auth';
import { useAuthStore } from '@/shared/stores';
import { ShellSkeleton } from './skeletons';

/**
 * The session could not be checked because the API did not answer. The cookie
 * may be valid, so the user is not sent to sign in again — only asked to retry.
 */
function SessionUnreachable() {
  const retry = (): void => {
    useAuthStore.getState().markChecking();
    void resumeSession();
  };

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <Result
        status="warning"
        title="Не вдалося перевірити сесію"
        subTitle="Сервер зараз не відповідає. Входити заново не потрібно — спробуйте ще раз за хвилину."
        extra={
          <Button type="primary" onClick={retry}>
            Спробувати ще
          </Button>
        }
      />
    </main>
  );
}

/**
 * Holds the protected area until the session state is known. Redirecting while
 * the status is still `unknown` would bounce every deep link on reload, because
 * the access token only exists in memory and the cookie has yet to be probed.
 */
export function RouteGuard({ children }: { children: ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status !== 'anonymous') return;
    // Carries the target along so the user lands where they aimed after signing in.
    const next = encodeURIComponent(pathname);
    router.replace(`/login?next=${next}`);
  }, [status, pathname, router]);

  if (status === 'unreachable') return <SessionUnreachable />;
  if (status !== 'authenticated') return <ShellSkeleton />;

  return <>{children}</>;
}
