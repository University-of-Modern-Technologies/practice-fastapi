'use client';

import { useTheme } from 'next-themes';
import { useSyncExternalStore } from 'react';

export type Appearance = 'light' | 'dark';

/** What the user chose; `system` follows the operating system. */
export type ThemePreference = Appearance | 'system';

interface AppTheme {
  readonly appearance: Appearance;
  readonly preference: ThemePreference;
  /** False until the client knows the stored preference. */
  readonly ready: boolean;
  setAppearance: (appearance: Appearance) => void;
  setPreference: (preference: ThemePreference) => void;
  toggle: () => void;
}

const noSubscription = () => () => {};

const isPreference = (value: string | undefined): value is ThemePreference =>
  value === 'light' || value === 'dark' || value === 'system';

/**
 * The stored preference is unknown during server rendering, so the first paint
 * must assume the light theme. Hydration is detected through the store snapshot
 * rather than an effect, which keeps the answer stable and avoids a second
 * render pass just to learn that the client is running.
 */
export const useAppTheme = (): AppTheme => {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const ready = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );

  const appearance: Appearance = ready && resolvedTheme === 'dark' ? 'dark' : 'light';
  const preference: ThemePreference = ready && isPreference(theme) ? theme : 'system';

  return {
    appearance,
    preference,
    ready,
    setAppearance: setTheme,
    setPreference: setTheme,
    toggle: () => setTheme(appearance === 'dark' ? 'light' : 'dark'),
  };
};
