'use client';

import type { FormInstance } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useUnsavedChanges } from './use-unsaved-changes';
import { useVersionConflict } from './use-version-conflict';

/** What a reload hands back: the shape of a TanStack `refetch()` result. */
interface ReloadResult<TRecord> {
  readonly data?: TRecord | undefined;
  /** A failed refetch still carries the old data, which must not pass for fresh. */
  readonly isError?: boolean;
}

interface UseRecordFormOptions<TRecord extends object, TValues> {
  readonly form: FormInstance<TValues>;
  /** The record as the cache holds it right now; absent on a create route. */
  readonly record: TRecord | undefined;
  /**
   * How a record fills the form. Every field the form edits must be a key of
   * the result, `undefined` included: a key left out would keep whatever the
   * previous snapshot put there. Must be stable — a module-level function.
   */
  readonly toValues: (record: TRecord) => Partial<TValues>;
  /** Re-reads the record; the fresh copy replaces the form's values and its version. */
  readonly onReload?: (() => Promise<ReloadResult<TRecord>>) | undefined;
}

interface UseRecordFormResult<TRecord> {
  /**
   * The snapshot the form was filled from. A save diffs against it and carries
   * its `version` — never the version of a copy the user has not seen.
   */
  readonly base: TRecord | undefined;
  readonly isDirty: boolean;
  /** Wire to the form's `onValuesChange`. */
  readonly markDirty: () => void;
  /** After a successful save: the answer becomes the snapshot and the form shows it. */
  readonly adopt: (saved: TRecord) => void;
  /** A save lost the race, or the record moved under unsaved edits. */
  readonly hasConflict: boolean;
  /** Returns true when the error was a lost race and is now shown. */
  readonly handleConflict: (error: unknown) => boolean;
  /** Discards the edits and shows the current record, with its current version. */
  readonly reload: () => void;
}

const versionOf = (record: object): number | undefined => {
  const version = (record as { readonly version?: unknown }).version;
  return typeof version === 'number' ? version : undefined;
};

/** Compared as the form sees them; a picker's dayjs value serialises to its instant. */
const sameValues = (left: unknown, right: unknown): boolean =>
  JSON.stringify(left) === JSON.stringify(right);

/**
 * Keeps an edit form, the record it was filled from and the version a save
 * sends in step with one another.
 *
 * antd reads `initialValues` once, at mount. Without this hook a refetch — a
 * re-read after a 409, a write elsewhere on the page, a live event — brings a
 * new `version` into the save while the fields keep the old values, and the
 * next save quietly writes those old values over somebody else's change.
 *
 * What happens when a fresher copy arrives depends on whether the user has
 * typed anything:
 *
 * - nothing typed — the form simply shows the fresh copy;
 * - edits on screen, and none of the fields they touch moved on the server —
 *   the edits stay and the newer version is taken: nothing is overwritten;
 * - edits on screen, and the server changed what the form shows — the edits
 *   stay, the old version stays with them, and the page says the record has
 *   moved. Saving now answers 409 rather than overwriting. The way out is a
 *   reload, which shows the current record and drops the edits.
 *
 * A record without a `version` is diffed field by field instead, so it never
 * conflicts: the snapshot is still kept, because the diff has to be taken
 * against the values the user actually edited.
 */
export const useRecordForm = <TRecord extends object, TValues>({
  form,
  record,
  toValues,
  onReload,
}: UseRecordFormOptions<TRecord, TValues>): UseRecordFormResult<TRecord> => {
  const [base, setBase] = useState<TRecord | undefined>(record);
  const [seen, setSeen] = useState<TRecord | undefined>(record);
  // A revision rather than the record alone: showing the same copy twice (a
  // reload that found nothing new) must still put its values back.
  const [shown, setShown] = useState<{ readonly record: TRecord | undefined; readonly at: number }>(
    { record, at: 0 },
  );
  const [isDirty, setIsDirty] = useState(false);
  const [hasMoved, setHasMoved] = useState(false);
  const { hasConflict, handleError, clearConflict } = useVersionConflict();

  useUnsavedChanges(isDirty);

  const show = (next: TRecord): void => {
    setBase(next);
    setShown((previous) => ({ record: next, at: previous.at + 1 }));
    setHasMoved(false);
  };

  // Decided while rendering, from the previous copy kept in state, so the
  // page never draws a frame where the version and the values disagree.
  if (record !== seen) {
    setSeen(record);

    if (record !== undefined) {
      const baseVersion = base === undefined ? undefined : versionOf(base);
      const nextVersion = versionOf(record);

      if (base === undefined || !isDirty) {
        show(record);
      } else if (baseVersion !== undefined && baseVersion === nextVersion) {
        // The same state of the record, re-read: nothing to reconcile. Without
        // a version there is no way to tell, so that case falls through.
        setBase(record);
      } else if (sameValues(toValues(base), toValues(record))) {
        // The server moved, but not in anything this form edits — the user's
        // edits apply to the new version as they would have to the old one.
        setBase(record);
      } else if (nextVersion !== undefined) {
        setHasMoved(true);
      }
    }
  }

  // Writing into the form is a side effect on antd's store, so it waits for
  // the commit instead of happening during render.
  useEffect(() => {
    if (shown.record === undefined || shown.at === 0) return;
    const values = toValues(shown.record) as Record<string, unknown>;
    form.setFields(
      Object.entries(values).map(([name, value]) => ({ name: name as never, value, errors: [] })),
    );
  }, [form, shown, toValues]);

  const markDirty = useCallback(() => setIsDirty(true), []);

  const adopt = useCallback(
    (saved: TRecord) => {
      setIsDirty(false);
      clearConflict();
      setBase(saved);
      setHasMoved(false);
      setShown((previous) => ({ record: saved, at: previous.at + 1 }));
    },
    [clearConflict],
  );

  const reload = useCallback(() => {
    if (!onReload) {
      clearConflict();
      return;
    }

    void onReload()
      .then(({ data, isError }) => {
        // A failed re-read leaves the explanation up: the edits and the old
        // version are still all the page has.
        if (isError === true || data === undefined) return;
        setIsDirty(false);
        clearConflict();
        setSeen(data);
        setBase(data);
        setHasMoved(false);
        setShown((previous) => ({ record: data, at: previous.at + 1 }));
      })
      .catch(() => undefined);
  }, [clearConflict, onReload]);

  return {
    base,
    isDirty,
    markDirty,
    adopt,
    hasConflict: hasConflict || hasMoved,
    handleConflict: handleError,
    reload,
  };
};
