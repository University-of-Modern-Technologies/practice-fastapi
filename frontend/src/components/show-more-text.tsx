'use client';

import { Tooltip } from 'antd';

interface ShowMoreTextProps {
  readonly text: string | null | undefined;
  /** How much fits in the cell before the text is cut. */
  readonly limit?: number;
}

/** Keeps a long note from stretching a table row to the height of a paragraph. */
export function ShowMoreText({ text, limit = 80 }: ShowMoreTextProps) {
  if (!text) return <span>—</span>;
  if (text.length <= limit) return <span>{text}</span>;

  return (
    <Tooltip title={text} styles={{ root: { maxWidth: 420 } }}>
      <span>{`${text.slice(0, limit).trimEnd()}…`}</span>
    </Tooltip>
  );
}
