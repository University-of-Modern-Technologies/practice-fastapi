'use client';

import {
  useCallback,
  useMemo,
  useSyncExternalStore,
  type HTMLAttributes,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import type { DataTableColumns } from './data-table.types';

const STORAGE_PREFIX = 'table:';
const MIN_WIDTH = 80;

type Widths = Record<string, number>;

const EMPTY_WIDTHS: Widths = {};

const storageKey = (tableId: string): string => `${STORAGE_PREFIX}${tableId}`;

const parseWidths = (raw: string | null): Widths => {
  if (!raw) return EMPTY_WIDTHS;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return EMPTY_WIDTHS;
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        ([, value]) => typeof value === 'number' && value >= MIN_WIDTH,
      ),
    ) as Widths;
  } catch {
    // A corrupted entry is not worth a crash — the table falls back to defaults.
    return EMPTY_WIDTHS;
  }
};

/**
 * Snapshots have to be referentially stable or the subscription re-renders
 * forever, so a parsed value is reused until the stored string itself changes.
 */
const snapshots = new Map<string, { raw: string | null; widths: Widths }>();
const listeners = new Set<() => void>();

const notify = (): void => {
  for (const listener of listeners) listener();
};

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const readWidths = (tableId: string): Widths => {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(storageKey(tableId));
  } catch {
    return EMPTY_WIDTHS;
  }

  const cached = snapshots.get(tableId);
  if (cached && cached.raw === raw) return cached.widths;

  const widths = parseWidths(raw);
  snapshots.set(tableId, { raw, widths });
  return widths;
};

/** The server has no stored widths, so it renders the defaults. */
const readServerWidths = (): Widths => EMPTY_WIDTHS;

const writeWidth = (tableId: string, key: string, width: number): void => {
  const next = { ...readWidths(tableId), [key]: width };
  try {
    window.localStorage.setItem(storageKey(tableId), JSON.stringify(next));
  } catch {
    // Storage may be full or blocked; the table simply forgets the new width.
    return;
  }
  notify();
};

interface ResizableCellProps extends HTMLAttributes<HTMLTableCellElement> {
  readonly columnKey?: string;
  readonly onResize?: (key: string, width: number) => void;
}

/**
 * Header cell with a drag handle on its trailing edge. The pointer is captured
 * for the duration of the drag, so the width keeps following the cursor even
 * once it leaves the narrow handle.
 */
function ResizableHeaderCell({ columnKey, onResize, children, ...rest }: ResizableCellProps) {
  const startResize = useCallback(
    (event: ReactPointerEvent<HTMLSpanElement>) => {
      if (!columnKey || !onResize) return;
      event.preventDefault();
      event.stopPropagation();

      const cell = event.currentTarget.closest('th');
      if (!cell) return;

      const startX = event.clientX;
      const startWidth = cell.getBoundingClientRect().width;
      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);

      const move = (moveEvent: globalThis.PointerEvent): void => {
        const width = Math.max(MIN_WIDTH, Math.round(startWidth + moveEvent.clientX - startX));
        onResize(columnKey, width);
      };

      const stop = (): void => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', stop);
        handle.removeEventListener('pointercancel', stop);
      };

      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', stop);
      handle.addEventListener('pointercancel', stop);
    },
    [columnKey, onResize],
  );

  return (
    <th {...rest} style={{ ...rest.style, position: 'relative' }}>
      {children}
      {columnKey && onResize ? (
        <span
          role="presentation"
          aria-hidden
          onPointerDown={startResize}
          className="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize touch-none select-none"
        />
      ) : null}
    </th>
  );
}

/**
 * Remembers how wide the operator made each column. A table someone has tuned
 * to their screen should still look that way tomorrow, and per-table storage
 * keeps one list from resizing another.
 */
export const useColumnSizing = <T,>(
  tableId: string,
  columns: DataTableColumns<T>,
): {
  sizedColumns: DataTableColumns<T>;
  headerCell: typeof ResizableHeaderCell;
} => {
  const widths = useSyncExternalStore(subscribe, () => readWidths(tableId), readServerWidths);

  const setWidth = useCallback(
    (key: string, width: number) => writeWidth(tableId, key, width),
    [tableId],
  );

  const sizedColumns = useMemo<DataTableColumns<T>>(
    () =>
      columns.map((column) => {
        const key = String(('key' in column ? column.key : undefined) ?? '');
        if (!key) return column;

        const stored = widths[key];
        return {
          ...column,
          ...(stored ? { width: stored } : {}),
          onHeaderCell: () => ({ columnKey: key, onResize: setWidth }) as never,
        };
      }),
    [columns, widths, setWidth],
  );

  return { sizedColumns, headerCell: ResizableHeaderCell };
};
