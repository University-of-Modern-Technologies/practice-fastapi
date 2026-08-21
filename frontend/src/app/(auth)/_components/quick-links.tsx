'use client';

import { Card, Col, Row, Typography } from 'antd';
import Link from 'next/link';
import { permissionScope, useAuthStore } from '@/shared/stores';
import { NAVIGATION, navigationLinks, visibleNavigation } from '@/templates/layouts';

/**
 * The sections this role may open. This block never depends on a report, so the
 * dashboard stays useful against an API build that has no analytics at all.
 */
export function QuickLinks() {
  const user = useAuthStore((state) => state.user);

  // The same visibility rule the sidebar applies, so a card can never offer a
  // page the menu hides — a nested screen states no permission of its own and
  // relies on the section above it.
  const available = navigationLinks(
    visibleNavigation(
      NAVIGATION,
      (node) => !node.permission || permissionScope(user, ...node.permission) !== null,
    ),
  ).filter((link) => link.href !== '/');

  return (
    <Row gutter={[16, 16]}>
      {available.map((item) => (
        <Col key={item.key} xs={24} sm={12} lg={8} xl={6}>
          <Link href={item.href}>
            <Card hoverable size="small">
              <div className="flex items-center gap-3">
                <span
                  className="grid size-10 shrink-0 place-items-center rounded-lg"
                  style={{ background: 'var(--crm-color-primary-bg)' }}
                >
                  {item.icon ? <item.icon size={20} /> : null}
                </span>
                <Typography.Text strong>{item.label}</Typography.Text>
              </div>
            </Card>
          </Link>
        </Col>
      ))}
    </Row>
  );
}
