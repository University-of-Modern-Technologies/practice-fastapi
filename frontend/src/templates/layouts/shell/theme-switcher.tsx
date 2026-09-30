'use client';

import { Button, Dropdown, Tooltip } from 'antd';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useAppTheme, type ThemePreference } from '../../hooks/use-app-theme';

const OPTIONS: readonly { key: ThemePreference; label: string; icon: typeof Sun }[] = [
  { key: 'light', label: 'Світла', icon: Sun },
  { key: 'dark', label: 'Темна', icon: Moon },
  { key: 'system', label: 'Як у системі', icon: Monitor },
];

export function ThemeSwitcher() {
  const { appearance, preference, setPreference } = useAppTheme();
  const Current = appearance === 'dark' ? Moon : Sun;

  return (
    <Dropdown
      trigger={['click']}
      placement="bottomRight"
      menu={{
        selectable: true,
        selectedKeys: [preference],
        items: OPTIONS.map(({ key, label, icon: Icon }) => ({
          key,
          label,
          icon: <Icon size={16} />,
        })),
        onClick: ({ key }) => setPreference(key as ThemePreference),
      }}
    >
      <Tooltip title="Тема" placement="bottom">
        <Button type="text" aria-label="Перемкнути тему" icon={<Current size={18} />} />
      </Tooltip>
    </Dropdown>
  );
}
