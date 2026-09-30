'use client';

import { usePathname } from 'next/navigation';
import { useMemo } from 'react';
import { permissionScope, useAuthStore } from '@/shared/stores';
import {
  NAVIGATION,
  activeNavigationKey,
  navigationLinks,
  navigationTrail,
  visibleNavigation,
  type NavigationLink,
  type NavigationNode,
} from '../navigation';

interface ShellNavigation {
  /** The tree the current user may see. */
  readonly visible: readonly NavigationNode[];
  readonly links: readonly NavigationLink[];
  readonly selectedKey: string | undefined;
  /** From the heading down to the active page; empty off the menu. */
  readonly trail: readonly NavigationNode[];
}

/** Everything the sidebar, the header and the search read about where the user is. */
export const useShellNavigation = (): ShellNavigation => {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);

  const visible = useMemo(
    () =>
      visibleNavigation(
        NAVIGATION,
        (node) => !node.permission || permissionScope(user, ...node.permission) !== null,
      ),
    [user],
  );
  const links = useMemo(() => navigationLinks(visible), [visible]);
  const selectedKey = activeNavigationKey(pathname, links);
  const trail = selectedKey ? navigationTrail(visible, selectedKey) : [];

  return { visible, links, selectedKey, trail };
};
