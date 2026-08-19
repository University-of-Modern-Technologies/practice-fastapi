import { Card, Col, Row, Skeleton } from 'antd';

interface DashboardSkeletonProps {
  readonly cards?: number;
}

/** Placeholder for the dashboard and the analytics route. */
export function DashboardSkeleton({ cards = 4 }: DashboardSkeletonProps) {
  return (
    <Row gutter={[16, 16]}>
      {Array.from({ length: cards }, (_, index) => (
        <Col key={index} xs={24} sm={12} xl={6}>
          <Card size="small">
            <Skeleton active paragraph={{ rows: 2 }} />
          </Card>
        </Col>
      ))}
    </Row>
  );
}
