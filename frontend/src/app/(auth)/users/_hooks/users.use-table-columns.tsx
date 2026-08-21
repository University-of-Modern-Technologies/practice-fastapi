'use client';

import { Space, Tag } from 'antd';
import { useMemo } from 'react';
import { DateValue, type DataTableColumns } from '@/components';
import type { User } from '../users.types';

/**
 * Columns of the users list. The API sorts nothing here, so no column claims a
 * sorter it cannot honour.
 */
export const useUsersTableColumns = (): DataTableColumns<User> =>
  useMemo(
    () => [
      {
        key: 'name',
        title: 'Імʼя',
        dataIndex: 'name',
        width: 220,
      },
      {
        key: 'email',
        title: 'Пошта',
        dataIndex: 'email',
        width: 260,
      },
      {
        key: 'roles',
        title: 'Ролі',
        width: 240,
        render: (_value, user: User) => (
          <Space size={4} wrap>
            {user.roles.length === 0 ? (
              <span>—</span>
            ) : (
              user.roles.map((role) => <Tag key={role.id}>{role.name}</Tag>)
            )}
          </Space>
        ),
      },
      {
        key: 'isActive',
        title: 'Стан',
        width: 120,
        render: (_value, user: User) =>
          user.isActive ? <Tag color="success">Активний</Tag> : <Tag color="error">Вимкнений</Tag>,
      },
      {
        key: 'createdAt',
        title: 'Створено',
        width: 140,
        render: (_value, user: User) => <DateValue value={user.createdAt} />,
      },
    ],
    [],
  );
