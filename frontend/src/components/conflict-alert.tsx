'use client';

import { Alert, Button } from 'antd';

interface ConflictAlertProps {
  readonly open: boolean;
  /** Re-reads the record so the form picks up the current version. */
  readonly onReload: () => void;
  readonly isReloading?: boolean;
}

/**
 * Shown when a save lost a race. The message names what happened and offers the
 * one move that resolves it; the values already typed stay on screen, so the
 * user re-reads and saves again rather than starting over.
 */
export function ConflictAlert({ open, onReload, isReloading = false }: ConflictAlertProps) {
  if (!open) return null;

  return (
    <Alert
      type="warning"
      showIcon
      className="mb-4"
      message="Запис змінив інший користувач"
      description="Щоб зберегти свої правки, перечитайте запис — введені значення залишаться."
      action={
        <Button size="small" loading={isReloading} onClick={onReload}>
          Перечитати
        </Button>
      }
    />
  );
}
