'use client';

import { Card, Skeleton, Space } from 'antd';

interface TablePageSkeletonProps {
  readonly rows?: number;
}

/** Placeholder for a list route while its first page is being read. */
export function TablePageSkeleton({ rows = 8 }: TablePageSkeletonProps) {
  return (
    <>
      <Skeleton.Input active style={{ width: 220, height: 28 }} className="mb-4" />
      <Card size="small">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Skeleton.Input active block style={{ height: 40 }} />
          {Array.from({ length: rows }, (_, index) => (
            <Skeleton.Input key={index} active block style={{ height: 32 }} />
          ))}
        </Space>
      </Card>
    </>
  );
}
