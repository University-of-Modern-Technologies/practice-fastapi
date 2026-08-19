'use client';

import { Modal } from 'antd';
import type { ReactNode } from 'react';

interface FormModalProps {
  readonly open: boolean;
  readonly title: string;
  readonly children: ReactNode;
  readonly isSaving?: boolean;
  readonly onSubmit: () => void;
  readonly onCancel: () => void;
  readonly submitLabel?: string;
  readonly width?: number;
  readonly danger?: boolean;
}

/**
 * A form in a dialog. Closing on a click outside is disabled on purpose: a
 * stray click must not throw away what the user has typed.
 */
export function FormModal({
  open,
  title,
  children,
  isSaving = false,
  onSubmit,
  onCancel,
  submitLabel = 'Зберегти',
  width = 560,
  danger = false,
}: FormModalProps) {
  return (
    <Modal
      open={open}
      title={title}
      width={width}
      maskClosable={false}
      destroyOnHidden
      onOk={onSubmit}
      onCancel={onCancel}
      okText={submitLabel}
      cancelText="Скасувати"
      confirmLoading={isSaving}
      okButtonProps={{ danger }}
    >
      {children}
    </Modal>
  );
}
