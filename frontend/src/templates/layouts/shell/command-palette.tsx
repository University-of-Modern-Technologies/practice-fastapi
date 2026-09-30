'use client';

import { Empty, Input, Modal, Typography } from 'antd';
import { CornerDownLeft, Search } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState, type KeyboardEvent } from 'react';
import { navigationTrail } from '../navigation';
import { useShellNavigation } from './use-shell-navigation';

interface CommandPaletteProps {
  readonly open: boolean;
  readonly onClose: () => void;
}

/**
 * Jump to any section the user may open, by typing part of its name or of the
 * heading above it. It searches the same tree the sidebar draws, so it offers
 * nothing the sidebar would hide.
 */
export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const router = useRouter();
  const { visible, links } = useShellNavigation();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);

  const entries = useMemo(
    () =>
      links.map((link) => {
        const trail = navigationTrail(visible, link.key);
        return {
          link,
          path: trail
            .slice(0, -1)
            .map((node) => node.label)
            .join(' / '),
        };
      }),
    [links, visible],
  );

  const needle = query.trim().toLocaleLowerCase('uk');
  const matches = needle
    ? entries.filter(({ link, path }) =>
        `${link.label} ${path}`.toLocaleLowerCase('uk').includes(needle),
      )
    : entries;

  const close = () => {
    setQuery('');
    setActive(0);
    onClose();
  };

  const go = (href: string) => {
    close();
    router.push(href);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, matches.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === 'Enter' && matches[active]) {
      event.preventDefault();
      go(matches[active].link.href);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={close}
      footer={null}
      closable={false}
      width={560}
      styles={{ container: { padding: 0, overflow: 'hidden' }, body: { padding: 0 } }}
      destroyOnHidden
      title={null}
    >
      <div className="p-3">
        <Input
          autoFocus
          size="large"
          variant="filled"
          prefix={<Search size={16} className="opacity-60" />}
          placeholder="Перейти до розділу…"
          aria-label="Пошук розділу"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      <ul
        role="listbox"
        aria-label="Розділи"
        className="m-0 max-h-96 list-none overflow-y-auto px-2 pb-2"
      >
        {matches.length === 0 ? (
          <li className="py-6">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Нічого не знайдено" />
          </li>
        ) : (
          matches.map(({ link, path }, index) => {
            const Icon = link.icon;
            const selected = index === active;
            return (
              <li key={link.key} role="option" aria-selected={selected}>
                <button
                  type="button"
                  onClick={() => go(link.href)}
                  onMouseMove={() => setActive(index)}
                  className="flex w-full cursor-pointer items-center gap-3 rounded-lg border-0 px-3 py-2 text-left text-inherit"
                  style={{
                    background: selected ? 'var(--crm-color-primary-bg)' : 'transparent',
                  }}
                >
                  {Icon ? (
                    <Icon size={16} strokeWidth={1.75} className="shrink-0 opacity-70" />
                  ) : null}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{link.label}</span>
                    {path ? (
                      <Typography.Text type="secondary" className="block truncate text-xs">
                        {path}
                      </Typography.Text>
                    ) : null}
                  </span>
                  {selected ? <CornerDownLeft size={14} className="shrink-0 opacity-50" /> : null}
                </button>
              </li>
            );
          })
        )}
      </ul>
    </Modal>
  );
}
