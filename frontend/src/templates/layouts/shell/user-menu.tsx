'use client';

import { Avatar, Dropdown, Tag, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { ChevronDown, LogOut, Settings } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useLogout } from '@/shared/auth';
import { permissionScope, useAuthStore } from '@/shared/stores';

/** Up to two initials, so "Avery Admin" reads as AA rather than a lone letter. */
const initials = (name: string | undefined): string =>
  (name ?? '')
    .split(/\s+/u)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('') || '?';

export function UserMenu({ compact = false }: { compact?: boolean }) {
  const user = useAuthStore((state) => state.user);
  const logout = useLogout();
  const router = useRouter();
  const canOpenSettings = permissionScope(user, 'settings', 'read') !== null;

  const items: MenuProps['items'] = [
    {
      key: 'profile',
      disabled: true,
      className: '!cursor-default',
      label: (
        <div className="flex max-w-64 flex-col gap-1 py-1">
          <Typography.Text strong ellipsis>
            {user?.name}
          </Typography.Text>
          <Typography.Text type="secondary" ellipsis className="text-xs">
            {user?.email}
          </Typography.Text>
          {user && user.roles.length > 0 ? (
            <span className="flex flex-wrap gap-1">
              {user.roles.map((role) => (
                <Tag key={role} color="purple" className="m-0">
                  {role}
                </Tag>
              ))}
            </span>
          ) : null}
        </div>
      ),
    },
    { type: 'divider' },
    ...(canOpenSettings
      ? [
          {
            key: 'settings',
            icon: <Settings size={16} />,
            label: 'Налаштування',
            onClick: () => router.push('/settings'),
          },
        ]
      : []),
    {
      key: 'logout',
      icon: <LogOut size={16} />,
      label: 'Вийти',
      danger: true,
      onClick: () => logout.mutate(),
    },
  ];

  return (
    <Dropdown trigger={['click']} placement="bottomRight" menu={{ items }}>
      {/* The visible text is the user's name, which is neither stable nor
          present on a narrow screen; the label keeps the control findable
          either way. */}
      <button
        type="button"
        aria-label="Обліковий запис"
        className="flex cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent px-1.5 py-1 text-inherit transition-colors hover:bg-[var(--crm-color-fill-tertiary)]"
      >
        <Avatar size={32} style={{ background: 'var(--crm-color-primary)', fontSize: 13 }}>
          {initials(user?.name)}
        </Avatar>
        {compact ? null : (
          <>
            <span className="max-w-40 truncate text-sm font-medium">{user?.name}</span>
            <ChevronDown size={14} className="opacity-60" />
          </>
        )}
      </button>
    </Dropdown>
  );
}
