'use client';

import { Table } from 'antd';
import { EmptyState } from '../empty-state';
import type { SimpleTableProps } from './data-table.types';

/**
 * For the handful of endpoints that answer with a bare array — settings, roles,
 * a user's sessions. Those collections are bounded by the domain rather than by
 * a page, so paging controls under them would promise something that does not
 * exist.
 */
export function SimpleTable<T extends object>({
  columns,
  rows,
  isLoading,
  rowKey,
  emptyText,
  emptyAction,
}: SimpleTableProps<T>) {
  return (
    <Table<T>
      size="small"
      rowKey={rowKey}
      columns={columns}
      dataSource={rows as T[] | undefined}
      loading={isLoading}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{
        emptyText: isLoading ? (
          <span />
        ) : (
          <EmptyState description={emptyText} action={emptyAction} />
        ),
      }}
    />
  );
}
