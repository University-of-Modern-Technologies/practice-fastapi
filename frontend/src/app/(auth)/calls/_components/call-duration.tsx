import { Tooltip } from 'antd';
import { EMPTY_VALUE } from '@/lib/date-time';

/**
 * Durations arrive as a whole number of seconds and the shared layer has no
 * formatter for them — `DateValue` renders instants, not spans. The two
 * functions below are the module's own for now; they carry nothing
 * call-specific, so a second section that measures a duration is the moment
 * they should move next to `DateTime` rather than be written again.
 */

const pad = (value: number): string => String(value).padStart(2, '0');

const isDuration = (seconds: number | null | undefined): seconds is number =>
  seconds !== null && seconds !== undefined && Number.isFinite(seconds) && seconds >= 0;

/**
 * `155` → `"2:35"`, `3725` → `"1:02:05"`. Clock form rather than words: a
 * column of durations is read by comparing them, and `"2 хв 35 с"` lines up
 * with nothing above it.
 *
 * Zero is a real value here and prints as `0:00` — an unanswered call lasted no
 * time, which is not the same as a duration nobody recorded.
 */
export const formatDuration = (seconds: number | null | undefined): string => {
  if (!isDuration(seconds)) return EMPTY_VALUE;

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;

  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`;
};

/** The same span in words, for the tooltip and for anywhere prose is read. */
export const spellDuration = (seconds: number | null | undefined): string => {
  if (!isDuration(seconds)) return EMPTY_VALUE;

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;

  const parts = [
    ...(hours > 0 ? [`${hours} год`] : []),
    ...(minutes > 0 ? [`${minutes} хв`] : []),
    // The seconds stay when they are all there is, so a very short call does
    // not come out as an empty string.
    ...(rest > 0 || total === 0 ? [`${rest} с`] : []),
  ];

  return parts.join(' ');
};

interface CallDurationProps {
  readonly seconds: number | null | undefined;
}

export function CallDuration({ seconds }: CallDurationProps) {
  const text = formatDuration(seconds);
  if (!isDuration(seconds)) return <span className="numeric">{text}</span>;

  return (
    <Tooltip title={spellDuration(seconds)}>
      <span className="numeric">{text}</span>
    </Tooltip>
  );
}
