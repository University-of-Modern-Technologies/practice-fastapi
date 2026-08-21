import type { Id, IsoDateTime } from '@/types/domain';

/**
 * The store is a closed registry, not a free-form bucket: the API accepts these
 * four keys and answers 400 `UNKNOWN_SETTING_KEY` for anything else. The list is
 * mirrored here so the editor can offer the field a key actually needs instead
 * of a raw JSON box for all of them.
 */
export const SETTING_KEYS = [
  'organization.name',
  'organization.defaultCurrency',
  'orders.numberPrefix',
  'warehouse.defaultCode',
] as const;

export type SettingKey = (typeof SETTING_KEYS)[number];

/** `default` means no row exists yet and the registry default is being served. */
export type SettingSource = 'database' | 'default';

export interface Setting {
  /**
   * Typed as a plain string on purpose: a key added on the server must still
   * render here, rather than break the list until the client catches up.
   */
  readonly key: string;
  readonly value: unknown;
  readonly description: string;
  readonly updatedById: Id | null;
  readonly updatedAt: IsoDateTime | null;
  readonly source: SettingSource;
}

export interface UpsertSettingInput {
  readonly value: unknown;
  readonly description?: string;
}

/** Codes the settings endpoints answer with, branched on rather than shown raw. */
export const SETTING_ERROR = {
  unknownKey: 'UNKNOWN_SETTING_KEY',
  invalidValue: 'INVALID_SETTING_VALUE',
} as const;
