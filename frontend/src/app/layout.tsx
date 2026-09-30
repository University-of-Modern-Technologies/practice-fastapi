import type { Metadata, Viewport } from 'next';
// Both faces ship as packages, so the build pulls nothing from a third-party
// CDN and the app renders identically in an isolated network.
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import './globals.css';
import { AppProviders } from '@/templates/providers';

export const metadata: Metadata = {
  title: 'CRM',
  description: 'Клієнт для роботи з контактами, угодами, замовленнями та складом',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // next-themes writes the theme class here after hydration; without
    // suppressHydrationWarning React reports the added class as a mismatch.
    <html lang="uk" suppressHydrationWarning>
      {/* "crm" is the scope class the component library declares its CSS
          variables on; carrying it on <body> makes them readable everywhere,
          not only inside a component. */}
      <body className="crm">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
