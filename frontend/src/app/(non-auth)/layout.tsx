import type { ReactNode } from 'react';
import { ThemeSwitcher } from '@/templates/layouts';

/** The public area: no shell, no session required. */
export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <main
      className="relative grid min-h-screen place-items-center p-4"
      style={{
        background:
          'radial-gradient(60rem 30rem at 50% -10%, var(--crm-color-primary-bg), transparent 70%), var(--crm-color-bg-layout)',
      }}
    >
      <div className="absolute top-4 right-4">
        <ThemeSwitcher />
      </div>
      {children}
    </main>
  );
}
