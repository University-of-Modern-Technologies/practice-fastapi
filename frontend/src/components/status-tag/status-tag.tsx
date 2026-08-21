import { Tag } from 'antd';
import { statusMeta, type StatusMeta } from '@/shared/constants';

interface StatusTagProps {
  /** The dictionary that owns this value — one of the maps in `enums.ts`. */
  readonly dictionary: Readonly<Record<string, StatusMeta>>;
  readonly value: string;
}

/**
 * Renders a state the API returned. A value the client has never heard of is
 * shown as itself rather than as a blank tag, so a state added on the server is
 * visible in the interface before anyone updates the dictionary.
 */
export function StatusTag({ dictionary, value }: StatusTagProps) {
  const { label, color } = statusMeta(dictionary, value);
  return <Tag color={color}>{label}</Tag>;
}
