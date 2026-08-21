'use client';

import { Select, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMemo } from 'react';
import { PERMISSION_SCOPE } from '@/shared/constants';
import {
  PERMISSION_ACTION_LABEL,
  PERMISSION_ACTIONS,
  PERMISSION_RESOURCE_LABEL,
  PERMISSION_RESOURCES,
  isKnownPermission,
  permissionKey,
  type PermissionGrant,
  type PermissionScope,
} from '../roles.types';

interface PermissionMatrixProps {
  readonly value: readonly PermissionGrant[];
  readonly onChange: (next: readonly PermissionGrant[]) => void;
  readonly disabled?: boolean;
}

interface MatrixRow {
  readonly id: string;
  readonly resource: string;
}

const SCOPE_OPTIONS = (Object.keys(PERMISSION_SCOPE) as PermissionScope[]).map((scope) => ({
  value: scope,
  label: PERMISSION_SCOPE[scope],
}));

const ROWS: readonly MatrixRow[] = PERMISSION_RESOURCES.map((resource) => ({
  id: resource,
  resource,
}));

/**
 * Resources down, actions across, the scope of the grant in the cell. A pair
 * the API does not know has no cell at all: offering it would only produce a
 * 400 `UNKNOWN_PERMISSION` on save.
 */
export function PermissionMatrix({ value, onChange, disabled = false }: PermissionMatrixProps) {
  const scopeByKey = useMemo(() => {
    const map = new Map<string, PermissionScope>();
    for (const grant of value) map.set(permissionKey(grant.resource, grant.action), grant.scope);
    return map;
  }, [value]);

  const setScope = (resource: string, action: string, scope: PermissionScope | undefined): void => {
    const rest = value.filter((grant) => !(grant.resource === resource && grant.action === action));
    onChange(scope ? [...rest, { resource, action, scope }] : rest);
  };

  const columns: ColumnsType<MatrixRow> = [
    {
      key: 'resource',
      title: 'Ресурс',
      width: 180,
      fixed: 'left',
      render: (_cell, row) => (
        <Typography.Text strong>
          {PERMISSION_RESOURCE_LABEL[row.resource] ?? row.resource}
        </Typography.Text>
      ),
    },
    ...PERMISSION_ACTIONS.map((action) => ({
      key: action,
      title: PERMISSION_ACTION_LABEL[action] ?? action,
      width: 160,
      render: (_cell: unknown, row: MatrixRow) =>
        isKnownPermission(row.resource, action) ? (
          <Select<PermissionScope>
            size="small"
            style={{ width: '100%' }}
            allowClear
            disabled={disabled}
            placeholder="немає"
            options={SCOPE_OPTIONS}
            value={scopeByKey.get(permissionKey(row.resource, action)) ?? null}
            onChange={(scope) => setScope(row.resource, action, scope ?? undefined)}
          />
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    })),
  ];

  return (
    <Table<MatrixRow>
      size="small"
      rowKey="id"
      columns={columns}
      dataSource={ROWS as MatrixRow[]}
      pagination={false}
      scroll={{ x: 'max-content' }}
    />
  );
}
