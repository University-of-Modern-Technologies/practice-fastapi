'use client';

import { Button, Popconfirm, Space, Table, Tag, Typography, type TableProps } from 'antd';
import { useEffect, useState } from 'react';
import {
  DateValue,
  EmptyState,
  PageHeader,
  PermissionGate,
  ShowMoreText,
  TablePageSkeleton,
} from '@/components';
import { useMutationFeedback, useReportError } from '@/shared/hooks';
import { SettingEditorModal } from './_components';
import { useResetSetting, useSettings } from './settings.queries';
import type { Setting } from './settings.types';
import { settingLabel, toDisplayValue } from './settings.validation';

function SettingsRegistry() {
  const [edited, setEdited] = useState<Setting | null>(null);
  const { data, isPending, isError, error } = useSettings();
  const reportError = useReportError();
  const { reportSuccess, reportFailure } = useMutationFeedback();
  const reset = useResetSetting();

  useEffect(() => {
    if (isError) reportError(error);
  }, [isError, error, reportError]);

  const resetSetting = (key: string) => {
    reset.mutate(key, {
      onSuccess: () => reportSuccess('Значення скинуто до стандартного'),
      onError: reportFailure,
    });
  };

  const columns: NonNullable<TableProps<Setting>['columns']> = [
    {
      key: 'key',
      title: 'Ключ',
      dataIndex: 'key',
      width: 260,
      render: (_value, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{settingLabel(row.key)}</Typography.Text>
          <Typography.Text type="secondary" className="numeric">
            {row.key}
          </Typography.Text>
        </Space>
      ),
    },
    {
      key: 'value',
      title: 'Значення',
      width: 240,
      render: (_value, row) => (
        <Typography.Text className="numeric">{toDisplayValue(row.value)}</Typography.Text>
      ),
    },
    {
      key: 'description',
      title: 'Опис',
      render: (_value, row) => <ShowMoreText text={row.description} limit={90} />,
    },
    {
      key: 'source',
      title: 'Джерело',
      width: 150,
      render: (_value, row) =>
        row.source === 'database' ? (
          <Tag color="processing">Змінено</Tag>
        ) : (
          <Tag>За замовчуванням</Tag>
        ),
    },
    {
      key: 'updatedAt',
      title: 'Змінено',
      width: 160,
      render: (_value, row) => <DateValue value={row.updatedAt} withTime />,
    },
    {
      key: 'actions',
      title: '',
      width: 190,
      align: 'right',
      render: (_value, row) => (
        <PermissionGate resource="settings" action="write" fallback={null}>
          <Space size="small">
            <Button size="small" onClick={() => setEdited(row)}>
              Змінити
            </Button>
            {/*
              A key still on its registry default has nothing stored to drop,
              so the reset is offered only where it would do something.
            */}
            {row.source === 'database' ? (
              <Popconfirm
                title="Скинути налаштування?"
                description="Значення повернеться до стандартного."
                okText="Скинути"
                cancelText="Скасувати"
                okButtonProps={{ loading: reset.isPending }}
                onConfirm={() => resetSetting(row.key)}
              >
                <Button size="small" danger>
                  Скинути
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        </PermissionGate>
      ),
    },
  ];

  if (isPending) return <TablePageSkeleton rows={4} />;

  return (
    <>
      <PageHeader
        title="Налаштування"
        description="Значення організації, які застосовуються до нових записів"
      />

      <Table<Setting>
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={data as Setting[] | undefined}
        // A closed registry of four keys: paging it would add a control that
        // never changes anything.
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyState description="Налаштувань ще немає" /> }}
      />

      <SettingEditorModal setting={edited} onClose={() => setEdited(null)} />
    </>
  );
}

export default function SettingsPage() {
  // The registry is a separate component so that a refused visitor never mounts
  // it: arriving by a direct link must show the notice, not a page firing
  // requests the API answers with 403.
  return (
    <PermissionGate resource="settings" action="read">
      <SettingsRegistry />
    </PermissionGate>
  );
}
