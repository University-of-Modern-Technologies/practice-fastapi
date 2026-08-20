'use client';

import { Popconfirm } from 'antd';
import type { ReactNode } from 'react';

interface DeleteConfirmProps {
  readonly onConfirm: () => void;
  readonly children: ReactNode;
  readonly title?: string;
  readonly description?: string;
  readonly isPending?: boolean;
  /** For actions that are irreversible without being a deletion. */
  readonly okText?: string;
}

/** One wording for deletion across the application, and never a bare click. */
export function DeleteConfirm({
  onConfirm,
  children,
  title = 'Видалити запис?',
  description = 'Дію не можна скасувати.',
  isPending = false,
  okText = 'Видалити',
}: DeleteConfirmProps) {
  return (
    <Popconfirm
      title={title}
      description={description}
      okText={okText}
      cancelText="Скасувати"
      okButtonProps={{ danger: true, loading: isPending }}
      onConfirm={onConfirm}
    >
      {children}
    </Popconfirm>
  );
}
