/**
 * The outline of the signed-in frame, shown while the session is restored.
 * It keeps the sidebar and the header where they are about to appear, so the
 * page does not jump from an empty screen to a full layout. Plain markup with
 * translucent fills, because it renders before the theme tokens are known.
 */
export function ShellSkeleton() {
  const bar = 'animate-pulse rounded-md bg-black/[0.06] dark:bg-white/[0.08]';

  return (
    <div className="flex min-h-screen" aria-busy="true" aria-label="Завантаження">
      <aside className="hidden w-[248px] shrink-0 flex-col gap-3 border-0 border-r border-solid border-black/[0.06] px-5 py-4 lg:flex dark:border-white/[0.08]">
        <div className="mb-4 flex items-center gap-2.5">
          <div className={`size-8 ${bar}`} />
          <div className={`h-4 w-16 ${bar}`} />
        </div>
        {Array.from({ length: 9 }, (_, index) => (
          <div
            key={index}
            className={`h-7 ${bar}`}
            style={{ width: `${60 + ((index * 17) % 35)}%` }}
          />
        ))}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-[60px] items-center gap-3 border-0 border-b border-solid border-black/[0.06] px-4 md:px-6 dark:border-white/[0.08]">
          <div className={`size-8 ${bar}`} />
          <div className={`h-4 w-40 ${bar}`} />
          <div className={`ml-auto hidden h-8 w-56 md:block ${bar}`} />
          <div className={`size-8 rounded-full ${bar}`} />
        </div>
        <div className="mx-auto w-full max-w-[1400px] p-4 md:p-6">
          <div className={`mb-2 h-7 w-64 ${bar}`} />
          <div className={`mb-8 h-4 w-96 max-w-full ${bar}`} />
          <div className="grid gap-4 md:grid-cols-3">
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className={`h-28 rounded-xl ${bar}`} />
            ))}
          </div>
          <div className={`mt-6 h-72 rounded-xl ${bar}`} />
        </div>
      </div>
    </div>
  );
}
