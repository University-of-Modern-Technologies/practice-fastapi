'use client';

import { Table } from 'antd';
import type { SorterResult } from 'antd/es/table/interface';
import { useMemo } from 'react';
import { EmptyState } from '../empty-state';
import type { DataTableColumns, DataTableProps } from './data-table.types';
import { useColumnSizing } from './data-table.use-column-sizing';

const PAGE_SIZE_OPTIONS = ['10', '20', '50', '100'];

/** Ant Design speaks `ascend`/`descend`; the API speaks `asc`/`desc`. */
const toWireOrder = (order: string | null | undefined): 'asc' | 'desc' | undefined => {
  if (order === 'ascend') return 'asc';
  if (order === 'descend') return 'desc';
  return undefined;
};

const toAntOrder = (order: string | undefined): 'ascend' | 'descend' | null => {
  if (order === 'asc') return 'ascend';
  if (order === 'desc') return 'descend';
  return null;
};

/**
 * The one table of the application. Every list is paged, sorted and filtered by
 * the API — the client never receives more rows than it shows, so a growing
 * dataset cannot turn a list page into a slow one.
 */
export function DataTable<T extends { readonly id: string }, F extends string = never>({
  tableId,
  columns,
  page,
  isLoading,
  params,
  onParamsChange,
  onRowClick,
  toolbar,
  emptyText,
  emptyAction,
  filters,
  expandable,
}: DataTableProps<T, F>) {
  // Reflects the active sort back onto its column, so the header arrow survives
  // a reload of a link that already carried the sorting in its query string.
  const orderedColumns = useMemo<DataTableColumns<T>>(
    () =>
      columns.map((column) => {
        const key = String(('key' in column ? column.key : undefined) ?? '');
        if (!key || !('sorter' in column) || !column.sorter) return column;
        return {
          ...column,
          sortOrder: key === params.sortBy ? toAntOrder(params.sortOrder) : null,
        };
      }),
    [columns, params.sortBy, params.sortOrder],
  );

  const { sizedColumns, headerCell } = useColumnSizing<T>(tableId, orderedColumns);

  const components = useMemo(() => ({ header: { cell: headerCell } }), [headerCell]);

  return (
    <div className="flex flex-col gap-3">
      {filters}
      {toolbar ? <div className="flex flex-wrap items-center gap-2">{toolbar}</div> : null}

      <Table<T>
        size="small"
        rowKey="id"
        columns={sizedColumns}
        components={components}
        dataSource={page?.items as T[] | undefined}
        loading={isLoading}
        sticky
        scroll={{ x: 'max-content' }}
        locale={{
          emptyText: isLoading ? (
            <span />
          ) : (
            <EmptyState description={emptyText} action={emptyAction} />
          ),
        }}
        {...(expandable ? { expandable } : {})}
        pagination={{
          current: params.page,
          pageSize: params.pageSize,
          total: page?.total ?? 0,
          showSizeChanger: true,
          pageSizeOptions: PAGE_SIZE_OPTIONS,
          showTotal: (total, [from, to]) => `${from}–${to} з ${total}`,
        }}
        onChange={(pagination, _filters, sorter) => {
          const single = (Array.isArray(sorter) ? sorter[0] : sorter) as
            SorterResult<T> | undefined;
          const sortBy = single?.columnKey === undefined ? undefined : String(single.columnKey);
          const sortOrder = toWireOrder(single?.order);

          onParamsChange({
            page: pagination.current,
            pageSize: pagination.pageSize,
            // A cleared sort has to remove both halves, or the API keeps
            // ordering by a column whose arrow is no longer lit.
            sortBy: sortOrder === undefined ? undefined : sortBy,
            sortOrder,
          } as never);
        }}
        {...(onRowClick
          ? {
              onRow: (row: T) => ({
                onClick: () => onRowClick(row),
                style: { cursor: 'pointer' },
              }),
            }
          : {})}
      />
    </div>
  );
}
