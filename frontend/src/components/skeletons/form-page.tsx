'use client';

import { Card, Skeleton, Space } from 'antd';

interface FormPageSkeletonProps {
  readonly fields?: number;
}

/** Placeholder for a card route while the record is being read. */
export function FormPageSkeleton({ fields = 6 }: FormPageSkeletonProps) {
  return (
    <Card>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {Array.from({ length: fields }, (_, index) => (
          <div key={index}>
            <Skeleton.Input active style={{ width: 140, height: 16 }} className="mb-2" />
            <Skeleton.Input active block style={{ height: 32 }} />
          </div>
        ))}
      </Space>
    </Card>
  );
}
