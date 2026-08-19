/** Every successful response carries its payload under `data`. */
export interface Envelope<T> {
  readonly data: T;
}

/** Shape returned by every list endpoint. Paging is done by the API, not here. */
export interface Page<T> {
  readonly items: readonly T[];
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
}

export type PermissionScope = 'ALL' | 'OWN';

export interface PermissionGrant {
  readonly resource: string;
  readonly action: string;
  readonly scope: PermissionScope;
}

export interface AuthenticatedUser {
  readonly id: string;
  readonly email: string;
  readonly name: string;
  readonly roles: readonly string[];
  readonly permissions: readonly PermissionGrant[];
}

export interface Session {
  readonly user: AuthenticatedUser;
  readonly accessToken: string;
  readonly accessTokenExpiresInSeconds: number;
}

/** Query parameters accepted by every list endpoint. */
export interface ListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly sortBy?: string;
  readonly sortOrder?: 'asc' | 'desc';
  readonly search?: string;
}

export const emptyPage = <T>(): Page<T> => ({ items: [], page: 1, pageSize: 20, total: 0 });
