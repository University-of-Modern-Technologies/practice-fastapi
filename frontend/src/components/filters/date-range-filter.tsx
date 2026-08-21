'use client';

import { DatePicker } from 'antd';
import type { Dayjs } from 'dayjs';
import { DateTime } from '@/lib/date-time';

interface DateRangeFilterProps {
  readonly from: string | undefined;
  readonly to: string | undefined;
  readonly onCommit: (range: { from: string | undefined; to: string | undefined }) => void;
  /** Instants carry a zone; calendar dates do not. Match what the API expects. */
  readonly mode?: 'date' | 'dateTime';
}

/**
 * The one place the `dayjs ↔ wire` conversion for a period lives. Audit,
 * movements and analytics all filter by a range, and each writing its own
 * conversion is three chances to send a local midnight as if it were UTC.
 */
export function DateRangeFilter({ from, to, onCommit, mode = 'date' }: DateRangeFilterProps) {
  const toWire = mode === 'dateTime' ? DateTime.toWireDateTime : DateTime.toWireDate;

  const value: [Dayjs | null, Dayjs | null] = [DateTime.toPicker(from), DateTime.toPicker(to)];

  return (
    <DatePicker.RangePicker
      value={value[0] === null && value[1] === null ? null : value}
      allowEmpty={[true, true]}
      placeholder={['Від', 'До']}
      onChange={(range) => onCommit({ from: toWire(range?.[0]), to: toWire(range?.[1]) })}
    />
  );
}
