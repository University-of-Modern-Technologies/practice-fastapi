'use client';

import { Result } from 'antd';
import type { ReactNode } from 'react';
import { useCanActOn } from '@/shared/hooks';

interface PermissionGateProps {
  readonly resource: string;
  readonly action: string;
  readonly children: ReactNode;
  /** Rendered instead of the refusal notice — use for inline controls. */
  readonly fallback?: ReactNode;
  /**
   * Owner of the record the control acts on. With it, an `OWN` grant opens the
   * gate only for the caller's own records, as the API would; without it, any
   * grant does. `null` is an unowned record, which `OWN` does not cover.
   */
  readonly ownerId?: string | null | undefined;
}

/**
 * Hides what the caller may not use. This is presentation only: the same rule
 * is enforced by the API, so bypassing the gate in devtools gains nothing.
 */
export function PermissionGate({
  resource,
  action,
  children,
  fallback,
  ownerId,
}: PermissionGateProps) {
  const allowed = useCanActOn(resource, action, ownerId);
  if (allowed) return <>{children}</>;
  if (fallback !== undefined) return <>{fallback}</>;

  return (
    <Result
      status="403"
      title="Недостатньо прав"
      subTitle="Ваша роль не має доступу до цього розділу."
    />
  );
}
