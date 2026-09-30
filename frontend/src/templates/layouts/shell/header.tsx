'use client';

import { Breadcrumb, Button, Layout, Tooltip } from 'antd';
import { Menu as MenuIcon, PanelLeft, Search } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { useUiStore } from '@/shared/stores';
import { Brand } from './brand';
import { CommandPalette } from './command-palette';
import { HEADER_HEIGHT } from './metrics';
import { ThemeSwitcher } from './theme-switcher';
import { useShellNavigation } from './use-shell-navigation';
import { UserMenu } from './user-menu';

const noSubscription = () => () => {};

/**
 * The platform's own modifier, for the hint on the search button. The server
 * cannot know it, so the first render says Ctrl and the client corrects it.
 */
const useShortcutLabel = (): string =>
  useSyncExternalStore(
    noSubscription,
    () => (/Mac|iPhone|iPad/u.test(navigator.platform) ? '⌘ K' : 'Ctrl K'),
    () => 'Ctrl K',
  );

/** Where the user is: the heading, the section and the page, the last one a link back to its list. */
function Location() {
  const pathname = usePathname();
  const { trail } = useShellNavigation();
  if (trail.length === 0) return null;

  const items = trail.map((node, index) => {
    const last = index === trail.length - 1;
    // The page itself is a link only from a record below it, e.g. a contact
    // card leads back to the list of contacts.
    const title =
      last && node.href && pathname !== node.href ? (
        <Link href={node.href}>{node.label}</Link>
      ) : (
        node.label
      );
    return { key: node.key, title };
  });

  return <Breadcrumb items={items} className="min-w-0 truncate" />;
}

export function Header({ mobile }: { mobile: boolean }) {
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const openMobileNav = useUiStore((state) => state.setMobileNavOpen);
  const [searchOpen, setSearchOpen] = useState(false);
  const shortcut = useShortcutLabel();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <Layout.Header
      className="sticky top-0 z-20 flex items-center gap-3 px-4 md:px-6"
      style={{
        height: HEADER_HEIGHT,
        lineHeight: 'normal',
        background: 'color-mix(in srgb, var(--crm-color-bg-container) 82%, transparent)',
        backdropFilter: 'saturate(180%) blur(12px)',
        borderBlockEnd: '1px solid var(--crm-color-border-secondary)',
      }}
    >
      {mobile ? (
        <>
          <Button
            type="text"
            aria-label="Відкрити меню"
            icon={<MenuIcon size={20} />}
            onClick={() => openMobileNav(true)}
          />
          <Link href="/" aria-label="На головну" className="text-inherit no-underline">
            <Brand />
          </Link>
        </>
      ) : (
        <>
          <Tooltip title={collapsed ? 'Розгорнути меню' : 'Згорнути меню'} placement="bottom">
            <Button
              type="text"
              aria-label={collapsed ? 'Розгорнути меню' : 'Згорнути меню'}
              icon={<PanelLeft size={18} />}
              onClick={toggleSidebar}
            />
          </Tooltip>
          <Location />
        </>
      )}

      <div className="ml-auto flex items-center gap-1.5">
        {mobile ? (
          <Button
            type="text"
            aria-label="Пошук розділу"
            icon={<Search size={18} />}
            onClick={() => setSearchOpen(true)}
          />
        ) : (
          <button
            type="button"
            aria-label="Пошук розділу"
            onClick={() => setSearchOpen(true)}
            className="mr-1 flex h-8 w-56 cursor-pointer items-center gap-2 rounded-lg border border-solid border-[var(--crm-color-border)] bg-[var(--crm-color-fill-quaternary)] px-3 text-[var(--crm-color-text-tertiary)] transition-colors hover:border-[var(--crm-color-primary-border-hover)]"
          >
            <Search size={15} />
            <span className="flex-1 text-left text-sm">Пошук…</span>
            <kbd className="rounded border border-solid border-[var(--crm-color-border)] bg-[var(--crm-color-bg-container)] px-1.5 font-sans text-[11px] leading-5">
              {shortcut}
            </kbd>
          </button>
        )}
        <ThemeSwitcher />
        <UserMenu compact={mobile} />
      </div>

      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
    </Layout.Header>
  );
}
