'use client';

import { Select, Typography } from 'antd';
import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
import { useDebouncedValue } from '@/shared/hooks';

/** Every directory this select reads is keyed by `id` on the wire. */
interface ReferenceRow {
  readonly id: string;
}

export interface ReferenceOptions<T> {
  readonly items: readonly T[];
  readonly isFetching: boolean;
  /**
   * Set by a source that can only read a capped slice of its directory. The
   * text is shown under the options, so a truncated list says so rather than
   * passing for the whole book.
   */
  readonly notice?: string | undefined;
}

export interface ReferenceSelectProps<T extends ReferenceRow> {
  /** Reads the page the search term matches. Owned by the calling module. */
  readonly useOptions: (search: string) => ReferenceOptions<T>;
  /** Reads the picked record on its own; see the note on `resolved` below. */
  readonly useResolved?: (id: string | undefined) => T | undefined;
  readonly getLabel: (row: T) => string;
  readonly getValue?: (row: T) => string;
  readonly placeholder?: string | undefined;
  readonly notFoundText?: string | undefined;
  readonly allowClear?: boolean | undefined;
  readonly disabled?: boolean | undefined;
  /** Supplied by `Form.Item`, which owns the value of the field. */
  readonly value?: string | null | undefined;
  readonly onChange?: ((next: string | undefined) => void) | undefined;
  /** For callers that need the record itself, not only its identifier. */
  readonly onSelectRow?: ((row: T | undefined) => void) | undefined;
}

/**
 * A source that has nothing to resolve. Declared once so the hook below is
 * always called: a `useResolved?.()` would be a conditional hook call.
 */
const useNoResolution = (): undefined => undefined;

/**
 * Puts a line under the options of a select whose source could not read the
 * whole directory. Exported because the warehouse pickers hit the same cap.
 */
export const renderSelectNotice = (menu: ReactNode, notice: string | undefined): ReactElement => (
  <>
    {menu}
    {notice === undefined ? null : (
      <div className="px-3 py-2">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {notice}
        </Typography.Text>
      </div>
    )}
  </>
);

/**
 * Picks one record out of a directory the API searches. The data source is a
 * prop rather than an import: this component belongs to the shared layer and
 * must not know which modules exist.
 */
export function ReferenceSelect<T extends ReferenceRow>({
  useOptions,
  useResolved = useNoResolution,
  getLabel,
  getValue = (row: T) => row.id,
  placeholder,
  notFoundText = 'Нічого не знайдено',
  allowClear = true,
  disabled = false,
  value,
  onChange,
  onSelectRow,
}: ReferenceSelectProps<T>) {
  const [search, setSearch] = useState('');
  // The search runs on the API, so a request per keystroke would make "Alex"
  // four requests whose three earlier answers may still land last.
  const settled = useDebouncedValue(search);

  const { items, isFetching, notice } = useOptions(settled);

  // An empty string is how a cleared text field arrives; it is not a selection.
  const selected = value === null || value === undefined || value === '' ? undefined : value;

  // The picked record may sit outside the page the search returned — when
  // editing, that is the usual case — so it is read on its own to keep the
  // field from showing a bare identifier.
  const resolved = useResolved(selected);

  const rows = useMemo(() => {
    const list = [...items];
    if (resolved && !list.some((row) => getValue(row) === getValue(resolved)))
      list.unshift(resolved);
    return list;
  }, [items, resolved, getValue]);

  const options = useMemo(
    () => rows.map((row) => ({ value: getValue(row), label: getLabel(row) })),
    [rows, getValue, getLabel],
  );

  const handleChange = (next: string | undefined): void => {
    onChange?.(next);
    onSelectRow?.(next === undefined ? undefined : rows.find((row) => getValue(row) === next));
  };

  return (
    <Select
      showSearch
      allowClear={allowClear}
      disabled={disabled}
      value={selected ?? null}
      options={options}
      loading={isFetching}
      // The list is narrowed on the server: filtering the page already fetched
      // by its label would hide every record the answer did not include.
      filterOption={false}
      onSearch={setSearch}
      // antd empties the visible search box on its own; without this the term
      // would keep narrowing the list the next time the field is opened.
      onOpenChange={(open) => {
        if (!open) setSearch('');
      }}
      onChange={handleChange}
      {...(placeholder === undefined ? {} : { placeholder })}
      popupRender={(menu) => renderSelectNotice(menu, notice)}
      notFoundContent={isFetching ? 'Пошук…' : notFoundText}
    />
  );
}
