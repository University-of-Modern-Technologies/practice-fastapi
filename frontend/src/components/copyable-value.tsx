'use client';

import { Typography } from 'antd';

interface CopyableValueProps {
  readonly value: string | null | undefined;
  /** Shown instead of the raw value — an identifier may be abbreviated. */
  readonly children?: string;
  /** Renders in the monospaced face: identifiers, codes, phone numbers. */
  readonly mono?: boolean;
}

/** A value the user will need elsewhere — an id, an SKU, a phone number. */
export function CopyableValue({ value, children, mono = true }: CopyableValueProps) {
  if (!value) return <span>—</span>;

  return (
    <Typography.Text copyable={{ text: value }} {...(mono ? { className: 'numeric' } : {})}>
      {children ?? value}
    </Typography.Text>
  );
}
