import { Empty } from 'antd';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  /** Says what is missing here, not the generic "no data". */
  readonly description?: string | undefined;
  /** The action that fills the emptiness — usually a create button. */
  readonly action?: ReactNode;
}

export function EmptyState({ description = 'Записів ще немає', action }: EmptyStateProps) {
  return (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description}>
      {action}
    </Empty>
  );
}
