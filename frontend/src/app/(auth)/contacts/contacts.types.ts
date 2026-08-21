import type { Id, Timestamps } from '@/types/domain';

/** A contact as the API returns it. Contacts carry no `version`. */
export interface Contact extends Timestamps {
  readonly id: Id;
  readonly ownerId: Id;
  readonly firstName: string;
  readonly lastName: string;
  readonly email: string | null;
  readonly phone: string | null;
  readonly company: string | null;
  readonly notes: string | null;
}

/** Columns the API is willing to sort by. Anything else answers 400. */
export const CONTACT_SORT_FIELDS = [
  'createdAt',
  'updatedAt',
  'firstName',
  'lastName',
  'company',
] as const;

export type ContactSortField = (typeof CONTACT_SORT_FIELDS)[number];

/** Filters this list keeps in the query string. */
export const CONTACT_FILTERS = ['search', 'ownerId'] as const;

export type ContactFilter = (typeof CONTACT_FILTERS)[number];

export interface ContactListQuery {
  readonly page?: number | undefined;
  readonly pageSize?: number | undefined;
  readonly search?: string | undefined;
  readonly ownerId?: Id | undefined;
  readonly sortBy?: ContactSortField | undefined;
  readonly sortOrder?: 'asc' | 'desc' | undefined;
}

export interface CreateContactInput {
  readonly ownerId?: Id | undefined;
  readonly firstName: string;
  readonly lastName: string;
  readonly email?: string | undefined;
  readonly phone?: string | undefined;
  readonly company?: string | undefined;
  readonly notes?: string | undefined;
}

/**
 * On update `undefined` and `null` mean different things: a field left out
 * keeps its stored value, while an explicit `null` clears it. `ownerId`,
 * `firstName` and `lastName` cannot be cleared — the API refuses null there.
 */
export interface UpdateContactInput {
  readonly ownerId?: Id | undefined;
  readonly firstName?: string | undefined;
  readonly lastName?: string | undefined;
  readonly email?: string | null | undefined;
  readonly phone?: string | null | undefined;
  readonly company?: string | null | undefined;
  readonly notes?: string | null | undefined;
}

/** What the form holds while it is being filled in. */
export interface ContactFormValues {
  readonly firstName: string;
  readonly lastName: string;
  readonly email?: string | undefined;
  readonly phone?: string | undefined;
  readonly company?: string | undefined;
  readonly notes?: string | undefined;
}

export const isContactSortField = (value: string | undefined): value is ContactSortField =>
  value !== undefined && (CONTACT_SORT_FIELDS as readonly string[]).includes(value);
