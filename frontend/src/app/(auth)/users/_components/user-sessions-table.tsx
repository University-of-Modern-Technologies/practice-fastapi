'use client';

import { Button, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DateValue, DeleteConfirm, EmptyState } from '@/components';
import { useMutationFeedback } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import { useRevokeSession, useUserSessions } from '../sessions.queries';
import type { UserSession } from '../users.types';

interface UserSessionsTableProps {
  readonly userId: Id;
  /** Revoking needs `users:update`; without it the column is not offered. */
  readonly canRevoke: boolean;
}

/**
 * Sessions arrive as a plain array — the endpoint has no paging — so this is a
 * simple table rather than the paged one used for lists.
 */
export function UserSessionsTable({ userId, canRevoke }: UserSessionsTableProps) {
  const sessions = useUserSessions(userId);
  const revoke = useRevokeSession(userId);
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const onRevoke = (sessionId: Id): void => {
    revoke.mutate(sessionId, {
      onSuccess: () => reportSuccess('Сесію відкликано'),
      onError: reportFailure,
    });
  };

  const columns: ColumnsType<UserSession> = [
    {
      key: 'createdAt',
      title: 'Створено',
      width: 160,
      render: (_value, session) => <DateValue value={session.createdAt} withTime />,
    },
    {
      key: 'expiresAt',
      title: 'Діє до',
      width: 160,
      render: (_value, session) => <DateValue value={session.expiresAt} withTime />,
    },
    {
      key: 'ipAddress',
      title: 'IP-адреса',
      width: 140,
      render: (_value, session) => <span className="numeric">{session.ipAddress ?? '—'}</span>,
    },
    {
      key: 'userAgent',
      title: 'Пристрій',
      render: (_value, session) =>
        session.userAgent ? (
          <Tooltip title={session.userAgent}>
            <Typography.Text ellipsis style={{ maxWidth: 260 }}>
              {session.userAgent}
            </Typography.Text>
          </Tooltip>
        ) : (
          '—'
        ),
    },
    {
      key: 'actions',
      title: '',
      width: 140,
      align: 'right',
      render: (_value, session) =>
        // An already revoked session has nothing left to take away.
        session.revokedAt ? (
          <Tag>Відкликано</Tag>
        ) : canRevoke ? (
          <DeleteConfirm
            title="Відкликати сесію?"
            description="Пристрій доведеться увійти знову."
            isPending={revoke.isPending}
            onConfirm={() => onRevoke(session.id)}
          >
            <Button size="small" danger>
              Відкликати
            </Button>
          </DeleteConfirm>
        ) : null,
    },
  ];

  return (
    <Table<UserSession>
      size="small"
      rowKey="id"
      columns={columns}
      dataSource={sessions.data as UserSession[] | undefined}
      loading={sessions.isLoading}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{
        emptyText: sessions.isLoading ? (
          <span />
        ) : (
          <EmptyState description="Активних сесій немає" />
        ),
      }}
    />
  );
}
