'use client';

import { Result } from 'antd';
import type { ReactNode } from 'react';
import { useHasPermission } from '@/shared/hooks';

interface PermissionGateProps {
  readonly resource: string;
  readonly action: string;
  readonly children: ReactNode;
  /** Rendered instead of the refusal notice — use for inline controls. */
  readonly fallback?: ReactNode;
}

/**
 * Hides what the caller may not use. This is presentation only: the same rule
 * is enforced by the API, so bypassing the gate in devtools gains nothing.
 */
export function PermissionGate({ resource, action, children, fallback }: PermissionGateProps) {
  const allowed = useHasPermission(resource, action);
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
