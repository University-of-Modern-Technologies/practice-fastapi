import { http } from '@/shared/api';
import type { Setting, UpsertSettingInput } from './settings.types';

const ROUTE = '/settings';

const keyPath = (key: string): string => `${ROUTE}/${encodeURIComponent(key)}`;

export const SettingsService = {
  /**
   * Answers a plain array, not a page: the registry is a closed set of four
   * keys and every one of them is always present, stored or defaulted.
   */
  list: (): Promise<readonly Setting[]> => http.get<readonly Setting[]>(ROUTE),

  getByKey: (key: string): Promise<Setting> => http.get<Setting>(keyPath(key)),

  /** Creates the row when the key has none yet, replaces the value otherwise. */
  update: (key: string, input: UpsertSettingInput): Promise<Setting> =>
    http.put<Setting>(keyPath(key), input),

  /**
   * Drops the stored row so the registry default applies again. It is a reset,
   * not a deletion: the key itself keeps existing and reading it still answers.
   * The API replies 204 with no body.
   */
  reset: (key: string): Promise<void> => http.delete<void>(keyPath(key)),
};
