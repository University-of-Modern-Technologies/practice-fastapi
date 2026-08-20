'use client';

import { App, ConfigProvider, theme } from 'antd';
import ukUA from 'antd/locale/uk_UA';
import dayjs from 'dayjs';
import 'dayjs/locale/uk';
import updateLocale from 'dayjs/plugin/updateLocale';
import type { ReactNode } from 'react';
import { FONT_FAMILY, PALETTE, RADIUS, SURFACE } from '@/shared/constants';
import { useAppTheme } from '../hooks/use-app-theme';

dayjs.extend(updateLocale);
dayjs.locale('uk');
// The API reports weeks starting on Monday; the pickers must agree with it.
dayjs.updateLocale('uk', { weekStart: 1 });

export function AntdProvider({ children }: { children: ReactNode }) {
  const { appearance } = useAppTheme();
  const surface = SURFACE[appearance];

  return (
    <ConfigProvider
      locale={ukUA}
      theme={{
        algorithm: appearance === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
        // Emitting CSS variables keeps the stylesheet stable across renders and
        // lets plain CSS read the same tokens the components use.
        cssVar: { key: 'crm' },
        hashed: false,
        token: {
          colorPrimary: PALETTE.primary,
          colorSuccess: PALETTE.success,
          colorWarning: PALETTE.warning,
          colorError: PALETTE.danger,
          colorInfo: PALETTE.info,
          colorBgLayout: surface.background,
          borderRadius: RADIUS,
          fontFamily: FONT_FAMILY,
          fontSize: 14,
        },
        components: {
          Layout: { bodyBg: surface.background, siderBg: surface.container },
          Menu: { itemBorderRadius: RADIUS, itemMarginInline: 8 },
          Card: { headerHeight: 48, bodyPadding: 16 },
          Table: { headerBorderRadius: RADIUS },
        },
      }}
    >
      <App>{children}</App>
    </ConfigProvider>
  );
}
