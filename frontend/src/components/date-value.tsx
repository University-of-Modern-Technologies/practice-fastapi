import { Tooltip } from 'antd';
import { DateTime } from '@/lib/date-time';

interface DateValueProps {
  readonly value: string | null | undefined;
  /** Adds the time to the visible text; otherwise it stays in the tooltip. */
  readonly withTime?: boolean;
}

export function DateValue({ value, withTime = false }: DateValueProps) {
  const text = withTime ? DateTime.toDateTime(value) : DateTime.toDate(value);
  if (!value) return <span className="numeric">{text}</span>;

  // The full instant is one hover away even in a column that shows only a date.
  return (
    <Tooltip title={DateTime.toDateTime(value)}>
      <span className="numeric">{text}</span>
    </Tooltip>
  );
}
