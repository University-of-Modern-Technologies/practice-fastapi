import { APP_NAME } from '@/shared/constants';

/** The product mark: a tile with the initial, and the name beside it unless `compact`. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <span
        aria-hidden
        className="grid size-8 shrink-0 place-items-center rounded-lg text-sm font-semibold text-white"
        style={{
          background:
            'linear-gradient(135deg, var(--crm-color-primary), var(--crm-color-primary-active))',
        }}
      >
        {APP_NAME.charAt(0)}
      </span>
      {compact ? null : (
        <span className="truncate text-base font-semibold tracking-tight">{APP_NAME}</span>
      )}
    </span>
  );
}
