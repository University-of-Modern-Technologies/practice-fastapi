import { http, type Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import type {
  Contact,
  ContactListQuery,
  CreateContactInput,
  UpdateContactInput,
} from './contacts.types';

const ROUTES = {
  collection: '/contacts',
  item: (id: Id): string => `/contacts/${id}`,
} as const;

/**
 * The only place that knows the shape of the contacts endpoints. It holds no
 * React, so its request paths and bodies can be asserted without a DOM.
 */
export const ContactsService = {
  list: (query: ContactListQuery = {}): Promise<Page<Contact>> =>
    http.get<Page<Contact>>(ROUTES.collection, {
      params: {
        page: query.page,
        pageSize: query.pageSize,
        search: query.search,
        ownerId: query.ownerId,
        sortBy: query.sortBy,
        sortOrder: query.sortOrder,
      },
    }),

  getById: (id: Id): Promise<Contact> => http.get<Contact>(ROUTES.item(id)),

  create: (input: CreateContactInput): Promise<Contact> =>
    http.post<Contact>(ROUTES.collection, input),

  /** Sends only the fields that changed; `null` clears one, absence keeps it. */
  update: (id: Id, input: UpdateContactInput): Promise<Contact> =>
    http.patch<Contact>(ROUTES.item(id), input),

  /** Soft delete. A contact carries no `version`, so nothing goes in the query. */
  remove: (id: Id): Promise<void> => http.delete<void>(ROUTES.item(id)),
};
