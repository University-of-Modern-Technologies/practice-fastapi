'use client';

import { Button, Card, Space } from 'antd';
import type { ReactNode } from 'react';
import { BackButton } from '../back-button';

interface FormCardProps {
  readonly title: string;
  readonly children: ReactNode;
  readonly isSaving?: boolean;
  /** Submits the form the card wraps; omitted for a read-only card. */
  readonly onSubmit?: () => void;
  readonly submitLabel?: string;
  /** Extra controls beside the save button — delete, transitions, and such. */
  readonly extra?: ReactNode;
  readonly backHref?: string;
}

/** The frame every create and edit page shares: heading, actions, one card. */
export function FormCard({
  title,
  children,
  isSaving = false,
  onSubmit,
  submitLabel = 'Зберегти',
  extra,
  backHref,
}: FormCardProps) {
  return (
    <Card
      title={title}
      extra={
        <Space wrap>
          {extra}
          {backHref ? <BackButton href={backHref} cancel /> : null}
          {onSubmit ? (
            <Button type="primary" loading={isSaving} onClick={onSubmit}>
              {submitLabel}
            </Button>
          ) : null}
        </Space>
      }
    >
      {children}
    </Card>
  );
}
