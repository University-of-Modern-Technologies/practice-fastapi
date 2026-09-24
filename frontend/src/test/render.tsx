import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App, ConfigProvider } from 'antd';
import ukUA from 'antd/locale/uk_UA';
import type { ReactElement, ReactNode } from 'react';
import type { AuthenticatedUser, PermissionGrant, PermissionScope } from '@/shared/api';
import { useAuthStore } from '@/shared/stores';

/**
 * Retries are off and nothing is ever stale: a test asserts on one settled
 * outcome, and a background refetch after the assertion only produces noise
 * that fails a neighbouring case.
 */
const createTestQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });

/**
 * Builds a grant list out of `'contacts:read'` shorthand. Written out by hand
 * the same list runs to five lines per test, which buries the one permission
 * the case is actually about.
 */
export const grants = (
  specs: readonly string[],
  scope: PermissionScope = 'ALL',
): readonly PermissionGrant[] =>
  specs.map((spec) => {
    const [resource = spec, action = 'read'] = spec.split(':');
    return { resource, action, scope };
  });

export const testUser = (overrides: Partial<AuthenticatedUser> = {}): AuthenticatedUser => ({
  id: '00000000-0000-0000-0000-000000000001',
  email: 'operator@example.test',
  name: 'Оператор',
  roles: ['manager'],
  permissions: [],
  ...overrides,
});

export interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  /** Signed-in user; pass `null` to render as anonymous. */
  readonly user?: AuthenticatedUser | null;
  /** Shorthand for `user` carrying exactly these grants. */
  readonly permissions?: readonly string[];
  readonly queryClient?: QueryClient;
}

/**
 * The one way a component enters a test. It supplies what the running app
 * supplies — the query cache, antd's locale and its `App` context, which
 * `useMutationFeedback` needs for `message` and `notification` — and puts the
 * auth store into a known state, since almost every screen reads a permission
 * before it decides what to draw.
 */
export const renderWithProviders = (
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderResult & { readonly queryClient: QueryClient } => {
  const { user, permissions, queryClient = createTestQueryClient(), ...rest } = options;

  const explicit = user !== undefined;
  const derived = permissions ? testUser({ permissions: grants(permissions) }) : null;
  const resolved = explicit ? user : derived;

  if (resolved) useAuthStore.getState().setUser(resolved);
  else useAuthStore.getState().clearSession();

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={ukUA} theme={{ hashed: false }}>
        <App>{children}</App>
      </ConfigProvider>
    </QueryClientProvider>
  );

  return { ...render(ui, { wrapper, ...rest }), queryClient };
};

/**
 * Route params for a page that reads them with `use()`. Marking the promise
 * settled the way React does spares every case a Suspense boundary that has
 * nothing to do with what is being asserted.
 */
export const routeParams = <T,>(value: T): Promise<T> =>
  Object.assign(Promise.resolve(value), { status: 'fulfilled', value });

export { screen, waitFor, within, act, fireEvent } from '@testing-library/react';
