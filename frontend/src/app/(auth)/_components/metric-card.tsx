'use client';

import { Card, Skeleton, Typography } from 'antd';
import type { ReactNode } from 'react';

interface MetricCardProps {
  readonly label: string;
  readonly value: ReactNode;
  readonly hint?: string;
  readonly isLoading: boolean;
}

/**
 * One figure of the overview. It keeps its own loading state so a slow report
 * holds up its own card rather than the whole page.
 */
export function MetricCard({ label, value, hint, isLoading }: MetricCardProps) {
  return (
    <Card size="small">
      {isLoading ? (
        <Skeleton active title={false} paragraph={{ rows: 2 }} />
      ) : (
        <div className="flex flex-col gap-1">
          <Typography.Text type="secondary">{label}</Typography.Text>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {value}
          </Typography.Title>
          {hint ? (
            <Typography.Text type="secondary" className="text-xs">
              {hint}
            </Typography.Text>
          ) : null}
        </div>
      )}
    </Card>
  );
}
