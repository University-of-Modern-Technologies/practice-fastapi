'use client';

import { Tag, Tooltip } from 'antd';

/**
 * Marks a payment a person took out of a match. The batch reconciliation skips
 * it from then on, so a run that leaves it untied is doing what it was told —
 * without the mark, the operator would expect the next run to tie it again.
 *
 * Neutral on purpose, like `UNMATCHED`: it records a decision, not a fault.
 */
export function AutoMatchDisabledTag() {
  return (
    <Tooltip title="Зведення зняла людина — автоматичне зведення цей платіж пропускає">
      <Tag>Без автозведення</Tag>
    </Tooltip>
  );
}
