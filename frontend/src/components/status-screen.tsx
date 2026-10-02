import type { ReactNode } from 'react';

interface StatusScreenProps {
  /** The product mark, passed in so this component stays free of the shell. */
  readonly brand: ReactNode;
  readonly children: ReactNode;
}

/**
 * A page that stands outside the signed-in frame — not found, a crash — but
 * still looks like the same product: the mark on top, the message centred.
 */
export function StatusScreen({ brand, children }: StatusScreenProps) {
  return (
    <main
      className="flex min-h-screen flex-col items-center justify-center gap-6 p-4"
      style={{ background: 'var(--crm-color-bg-layout)' }}
    >
      {brand}
      <div
        className="w-full max-w-lg rounded-2xl border border-solid px-6 py-2"
        style={{
          background: 'var(--crm-color-bg-container)',
          borderColor: 'var(--crm-color-border-secondary)',
        }}
      >
        {children}
      </div>
    </main>
  );
}
