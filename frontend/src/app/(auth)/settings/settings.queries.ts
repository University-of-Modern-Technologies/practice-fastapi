'use client';

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { SettingsService } from './settings.service';
import type { Setting, UpsertSettingInput } from './settings.types';

export const settingsKeys = {
  all: ['settings'] as const,
  list: () => [...settingsKeys.all, 'list'] as const,
  detail: (key: string) => [...settingsKeys.all, 'detail', key] as const,
};

export const useSettings = (): UseQueryResult<readonly Setting[]> =>
  useQuery({
    queryKey: settingsKeys.list(),
    queryFn: () => SettingsService.list(),
  });

export const useSetting = (key: string): UseQueryResult<Setting> =>
  useQuery({
    queryKey: settingsKeys.detail(key),
    queryFn: () => SettingsService.getByKey(key),
    enabled: key !== '',
  });

export interface UpdateSettingVariables {
  readonly key: string;
  readonly input: UpsertSettingInput;
}

export const useUpdateSetting = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ key, input }: UpdateSettingVariables) => SettingsService.update(key, input),
    // Other modules read these values through their own calls, so the whole
    // branch is dropped rather than only the row that was written.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.all }),
  });
};

export const useResetSetting = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (key: string) => SettingsService.reset(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.all }),
  });
};
