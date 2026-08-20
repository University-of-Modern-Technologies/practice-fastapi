'use client';

import { useTheme } from 'next-themes';
import { useSyncExternalStore } from 'react';

export type Appearance = 'light' | 'dark';

interface AppTheme {
  readonly appearance: Appearance;
  /** False until the client knows the stored preference. */
  readonly ready: boolean;
  setAppearance: (appearance: Appearance) => void;
  toggle: () => void;
}

const noSubscription = () => () => {};

/**
 * The stored preference is unknown during server rendering, so the first paint
 * must assume the light theme. Hydration is detected through the store snapshot
 * rather than an effect, which keeps the answer stable and avoids a second
 * render pass just to learn that the client is running.
 */
export const useAppTheme = (): AppTheme => {
  const { resolvedTheme, setTheme } = useTheme();
  const ready = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );

  const appearance: Appearance = ready && resolvedTheme === 'dark' ? 'dark' : 'light';

  return {
    appearance,
    ready,
    setAppearance: setTheme,
    toggle: () => setTheme(appearance === 'dark' ? 'light' : 'dark'),
  };
};
