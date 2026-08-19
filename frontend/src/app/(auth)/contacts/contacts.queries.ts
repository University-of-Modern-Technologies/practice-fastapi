'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Id } from '@/types/domain';
import { ContactsService } from './contacts.service';
import type {
  Contact,
  ContactListQuery,
  CreateContactInput,
  UpdateContactInput,
} from './contacts.types';

/**
 * Hierarchical keys let a write invalidate exactly what it touched: saving one
 * contact refreshes the lists and that one card, not every cached answer in the
 * application.
 */
export const contactsKeys = {
  all: ['contacts'] as const,
  lists: () => [...contactsKeys.all, 'list'] as const,
  list: (params: ContactListQuery) => [...contactsKeys.lists(), params] as const,
  details: () => [...contactsKeys.all, 'detail'] as const,
  detail: (id: Id) => [...contactsKeys.details(), id] as const,
};

export const useContactsList = (query: ContactListQuery) =>
  useQuery({
    queryKey: contactsKeys.list(query),
    queryFn: () => ContactsService.list(query),
    // Paging keeps the previous rows on screen instead of flashing a skeleton
    // between two pages of the same list.
    placeholderData: keepPreviousData,
  });

export const useContact = (id: Id | undefined) =>
  useQuery({
    queryKey: contactsKeys.detail(id ?? ''),
    queryFn: () => ContactsService.getById(id as Id),
    enabled: Boolean(id),
  });

/** How the book names a person wherever a contact is picked rather than read. */
export const contactLabel = (contact: Contact): string =>
  [`${contact.firstName} ${contact.lastName}`.trim(), contact.company]
    .filter((part) => part)
    .join(' · ');

/** One page is what a picker shows; the term narrows it on the server. */
const REFERENCE_PAGE_SIZE = 20;

/** Feeds a reference picker: the search is the one the list page performs. */
export const useContactOptions = (
  search: string,
): { items: readonly Contact[]; isFetching: boolean } => {
  const { data, isFetching } = useContactsList({
    page: 1,
    pageSize: REFERENCE_PAGE_SIZE,
    ...(search ? { search } : {}),
  });

  return { items: data?.items ?? [], isFetching };
};

export const useResolvedContact = (id: Id | undefined): Contact | undefined => useContact(id).data;

export const useCreateContact = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateContactInput) => ContactsService.create(input),
    onSuccess: (created: Contact) => {
      queryClient.setQueryData(contactsKeys.detail(created.id), created);
      void queryClient.invalidateQueries({ queryKey: contactsKeys.lists() });
    },
  });
};

export const useUpdateContact = (id: Id) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateContactInput) => ContactsService.update(id, input),
    onSuccess: (updated: Contact) => {
      queryClient.setQueryData(contactsKeys.detail(id), updated);
      void queryClient.invalidateQueries({ queryKey: contactsKeys.lists() });
    },
  });
};

export const useDeleteContact = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: Id) => ContactsService.remove(id),
    onSuccess: (_result, id) => {
      // The record is gone; keeping its card cached would show a ghost.
      queryClient.removeQueries({ queryKey: contactsKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: contactsKeys.lists() });
    },
  });
};
