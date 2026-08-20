'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ApiError } from '@/shared/api';

/**
 * Retrying a rejected request is pointless: a 400 stays a 400, a 403 stays a
 * 403. Only transport failures and server faults are worth a second attempt.
 */
const shouldRetry = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= 2) return false;
  if (!(error instanceof ApiError)) return false;
  return error.status === 0 || error.status >= 500;
};

const createQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        // Lists are re-read on demand and after mutations, not on every focus
        // change — an operator switching windows should not restart the table.
        refetchOnWindowFocus: false,
        staleTime: 30_000,
      },
      mutations: { retry: false },
    },
  });

export function QueryProvider({ children }: { children: ReactNode }) {
  // Held in state so a re-render never swaps the cache out from under the tree.
  const [queryClient] = useState(createQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
