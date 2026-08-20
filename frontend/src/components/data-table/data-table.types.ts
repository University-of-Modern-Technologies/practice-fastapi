import type { TableProps } from 'antd';
import type { ReactNode } from 'react';
import type { Page } from '@/shared/api';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';

export type DataTableColumns<T> = NonNullable<TableProps<T>['columns']>;

export interface DataTableProps<T extends { readonly id: string }, F extends string = never> {
  /** Identifies the table when its column widths are stored between visits. */
  readonly tableId: string;
  readonly columns: DataTableColumns<T>;
  /** The page the API returned, or nothing while the first read is running. */
  readonly page: Page<T> | undefined;
  readonly isLoading: boolean;
  readonly params: ListParams<F>;
  readonly onParamsChange: (patch: ListParamsPatch<F>) => void;
  readonly onRowClick?: (row: T) => void;
  /** Placed to the right of the paging summary, above the table. */
  readonly toolbar?: ReactNode;
  readonly emptyText?: string;
  /** Offered inside the empty state — usually the create button. */
  readonly emptyAction?: ReactNode;
  /** Rendered under the toolbar — the filter row belongs here. */
  readonly filters?: ReactNode;
  /** Row expansion, for journals whose payload does not fit a cell. */
  readonly expandable?: TableProps<T>['expandable'];
}

export interface SimpleTableProps<T> {
  readonly columns: DataTableColumns<T>;
  /** Endpoints that answer with a bare array rather than a page. */
  readonly rows: readonly T[] | undefined;
  readonly isLoading: boolean;
  /** A field name, or a function when the identity is a composite of fields. */
  readonly rowKey: (keyof T & string) | ((row: T) => string);
  readonly emptyText?: string;
  readonly emptyAction?: ReactNode;
}
