'use client';

import { Alert, Button } from 'antd';

interface ConflictAlertProps {
  readonly open: boolean;
  /** Re-reads the record so the form shows the current values with the current version. */
  readonly onReload: () => void;
  readonly isReloading?: boolean;
}

/**
 * Shown when a save lost a race, or when the record moved under unsaved edits.
 * The message names what happened and offers the one move that resolves it.
 * It says plainly that the edits go: a re-read that kept them would pair the
 * old values with the new version, and the next save would write them over
 * whatever the other person changed.
 */
export function ConflictAlert({ open, onReload, isReloading = false }: ConflictAlertProps) {
  if (!open) return null;

  return (
    <Alert
      type="warning"
      showIcon
      className="mb-4"
      message="Запис змінив інший користувач"
      description="Перечитайте запис, щоб побачити його поточний стан. Незбережені правки буде скинуто — внесіть їх ще раз, якщо вони досі потрібні."
      action={
        <Button size="small" loading={isReloading} onClick={onReload}>
          Перечитати
        </Button>
      }
    />
  );
}
