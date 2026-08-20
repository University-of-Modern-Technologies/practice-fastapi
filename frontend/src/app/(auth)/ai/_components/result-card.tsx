'use client';

import { Card, Space, Tag, Tooltip, Typography } from 'antd';
import type { ReactNode } from 'react';
import { DateTime } from '@/lib/date-time';
import type { IsoDateTime } from '@/types/domain';

interface ResultCardProps {
  readonly title: string;
  readonly provider: string;
  readonly cached: boolean;
  /** When this answer reached the client — the model is slow enough to matter. */
  readonly receivedAt: IsoDateTime;
  readonly children: ReactNode;
}

/**
 * The frame both answers share. Provider, cache state and time are the three
 * things a user needs to read an assistant answer honestly: who produced it,
 * whether it was produced just now, and how old the text on screen is.
 */
export function ResultCard({ title, provider, cached, receivedAt, children }: ResultCardProps) {
  return (
    <Card
      size="small"
      title={title}
      extra={
        cached ? (
          <Tooltip title="Відповідь узято з кешу сервера: повторний однаковий запит не звертається до моделі, тому текст той самий і зʼявляється миттєво.">
            <Tag color="processing">З кешу</Tag>
          </Tooltip>
        ) : null
      }
    >
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        {children}

        {/* Diagnostic line: who answered and when — a caption, never a heading. */}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {`Модель: ${provider} · ${DateTime.toDateTime(receivedAt)}`}
        </Typography.Text>
      </Space>
    </Card>
  );
}
