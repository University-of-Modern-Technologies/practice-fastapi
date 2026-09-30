// Layout and framing
export { PageHeader } from './page-header';
export { BackButton } from './back-button';
export {
  FormCard,
  FormModal,
  ReferenceSelect,
  applyServerErrors,
  renderSelectNotice,
  requiredRule,
  zodRule,
  type ReferenceOptions,
  type ReferenceSelectProps,
} from './form';

// Data display
export {
  DataTable,
  SimpleTable,
  type DataTableColumns,
  type DataTableProps,
  type SimpleTableProps,
} from './data-table';
export { DateRangeFilter, TextFilter } from './filters';
export { StatusTag } from './status-tag';
export { MoneyValue } from './money-value';
export { DateValue } from './date-value';
export { CopyableValue } from './copyable-value';
export { ShowMoreText } from './show-more-text';
export { EmptyState } from './empty-state';
export { DetailsCard, DetailsItem } from './details-card';
export { ModuleUnavailable } from './module-unavailable';

// Access and safety
export { PermissionGate } from './permission-gate';
export { RouteGuard } from './route-guard';
export { DeleteConfirm } from './delete-confirm';
export { ConflictAlert } from './conflict-alert';

// Loading placeholders
export { DashboardSkeleton, FormPageSkeleton, ShellSkeleton, TablePageSkeleton } from './skeletons';
