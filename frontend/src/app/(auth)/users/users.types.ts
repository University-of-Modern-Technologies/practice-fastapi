import type { Id, IsoDateTime, Timestamps } from '@/types/domain';

/** A role as it appears on a user — the full definition lives in `/roles`. */
export interface UserRole {
  readonly id: Id;
  readonly name: string;
}

/**
 * The API never returns the password hash, not even to an administrator, so
 * there is no field for it here and nothing to accidentally render.
 */
export interface User extends Timestamps {
  readonly id: Id;
  readonly email: string;
  readonly name: string;
  readonly isActive: boolean;
  readonly roles: readonly UserRole[];
}

/** An issued refresh session. `revokedAt` set means it can no longer renew. */
export interface UserSession extends Timestamps {
  readonly id: Id;
  readonly userId: Id;
  readonly expiresAt: IsoDateTime;
  readonly revokedAt: IsoDateTime | null;
  readonly ipAddress: string | null;
  readonly userAgent: string | null;
}

export interface UsersListQuery {
  readonly page: number;
  readonly pageSize: number;
}

export interface CreateUserInput {
  readonly email: string;
  readonly name: string;
  readonly password: string;
  readonly roleIds: readonly Id[];
}

/** Every field is optional, but the API refuses a body without at least one. */
export interface UpdateUserInput {
  readonly email?: string;
  readonly name?: string;
  readonly password?: string;
  readonly roleIds?: readonly Id[];
}

/** The shape the form holds. Ant Design writes into the arrays, so `roleIds`
 *  is a plain array while the fields themselves stay read-only. */
export interface UserFormValues {
  readonly email: string;
  readonly name: string;
  readonly password?: string;
  readonly roleIds: Id[];
}
