'use client';

import { Input } from 'antd';

interface TextFilterProps {
  readonly value: string | undefined;
  /** Called when the value is committed, not on every keystroke. */
  readonly onCommit: (value: string | undefined) => void;
  readonly placeholder?: string;
  readonly width?: number;
}

/**
 * A text filter that commits on Enter, on blur, and on clear — never while the
 * user is still typing. Firing a request per keystroke would put the list on
 * every prefix of the word, and the answer to "Ale" is noise on the way to "Alex".
 *
 * The field is uncontrolled on purpose: the value lives in the query string,
 * and mirroring it back into React state would need an effect that the linter —
 * rightly — refuses.
 */
export function TextFilter({ value, onCommit, placeholder, width = 220 }: TextFilterProps) {
  const commit = (next: string): void => {
    const trimmed = next.trim();
    if (trimmed === (value ?? '')) return;
    onCommit(trimmed === '' ? undefined : trimmed);
  };

  return (
    <Input.Search
      // Remounts when the query string changes underneath — a reset or a shared
      // link then shows what the list is actually filtered by.
      key={value ?? ''}
      defaultValue={value ?? ''}
      placeholder={placeholder ?? 'Пошук'}
      allowClear
      style={{ width }}
      onSearch={commit}
      onBlur={(event) => commit(event.target.value)}
    />
  );
}
