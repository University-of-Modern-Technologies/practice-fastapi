import type { ReactNode } from 'react';

/** The public area: no shell, no session required. */
export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <main
      className="grid min-h-screen place-items-center p-4"
      style={{ background: 'var(--crm-color-bg-layout)' }}
    >
      {children}
    </main>
  );
}
