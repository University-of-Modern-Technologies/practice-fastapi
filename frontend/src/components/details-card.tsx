'use client';

import { Descriptions } from 'antd';
import type { ReactNode } from 'react';

interface DetailsCardProps {
  /** Optional: sections that already sit inside a titled `Card` pass nothing. */
  readonly title?: ReactNode;
  readonly extra?: ReactNode;
  /** `DetailsItem` elements — the same component `Descriptions` expects. */
  readonly children: ReactNode;
}

/**
 * A read-only block of label/value pairs. The settings are fixed here rather
 * than repeated at each call site, so two panels showing the same kind of
 * record cannot end up with different densities or breakpoints.
 */
export function DetailsCard({ title, extra, children }: DetailsCardProps) {
  return (
    <Descriptions
      size="small"
      bordered
      column={{ xs: 1, sm: 2 }}
      {...(title ? { title } : {})}
      {...(extra ? { extra } : {})}
    >
      {children}
    </Descriptions>
  );
}

/** Re-exported as is: `Descriptions` matches its items by component identity. */
export const DetailsItem = Descriptions.Item;
