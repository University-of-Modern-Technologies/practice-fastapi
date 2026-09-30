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
  const dark = appearance === 'dark';

  return (
    <ConfigProvider
      locale={ukUA}
      theme={{
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        // Emitting CSS variables keeps the stylesheet stable across renders and
        // lets plain CSS read the same tokens the components use. The prefix is
        // what names the variables (--crm-color-primary); the key only names
        // the scope class, which the root layout puts on <body>.
        cssVar: { key: 'crm', prefix: 'crm' },
        hashed: false,
        token: {
          colorPrimary: PALETTE.primary,
          colorSuccess: PALETTE.success,
          colorWarning: PALETTE.warning,
          colorError: PALETTE.danger,
          colorInfo: PALETTE.info,
          // antd derives links from the info colour; a sky-blue link beside
          // indigo buttons reads as a second brand. The dark theme needs a
          // lighter shade to stay readable on its near-black surfaces.
          colorLink: dark ? '#818CF8' : PALETTE.primary,
          colorBgLayout: surface.background,
          borderRadius: RADIUS,
          fontFamily: FONT_FAMILY,
          fontSize: 14,
        },
        components: {
          Layout: { bodyBg: surface.background, siderBg: surface.container },
          Menu: {
            itemBorderRadius: RADIUS,
            itemMarginInline: 10,
            itemHeight: 38,
            itemBg: 'transparent',
            subMenuItemBg: 'transparent',
            // The default selected colours are the primary on its own tint, which
            // in the dark theme is indigo on near-indigo; a lighter text keeps
            // the current page readable in both.
            itemSelectedBg: dark ? 'rgba(129, 140, 248, 0.16)' : '#EEF2FF',
            itemSelectedColor: dark ? '#C7D2FE' : PALETTE.primary,
            itemHoverBg: dark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(15, 23, 42, 0.04)',
            groupTitleColor: dark ? 'rgba(255, 255, 255, 0.45)' : 'rgba(15, 23, 42, 0.45)',
            groupTitleFontSize: 12,
          },
          Breadcrumb: { lastItemColor: surface.text, fontSize: 14 },
          Card: { headerHeight: 48, bodyPadding: 16 },
          Table: { headerBorderRadius: RADIUS },
        },
      }}
    >
      <App>{children}</App>
    </ConfigProvider>
  );
}
