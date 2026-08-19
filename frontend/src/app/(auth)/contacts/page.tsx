'use client';

import { Button, Card } from 'antd';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import { DataTable, EmptyState, PageHeader, PermissionGate } from '@/components';
import { useListParams, useMutationFeedback } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import { useContactsList, useDeleteContact } from './contacts.queries';
import {
  CONTACT_FILTERS,
  isContactSortField,
  type Contact,
  type ContactFilter,
  type ContactListQuery,
} from './contacts.types';
import {
  hasActiveContactFilters,
  useContactsTableColumns,
  useContactsTableFilters,
} from './_hooks';

const LIST_DEFAULTS = { sortBy: 'createdAt', sortOrder: 'desc' } as const;

function ContactsList() {
  const router = useRouter();
  const { params, setParams, resetParams } = useListParams<ContactFilter>({
    filters: CONTACT_FILTERS,
    defaults: LIST_DEFAULTS,
  });

  const query = useMemo<ContactListQuery>(
    () => ({
      page: params.page,
      pageSize: params.pageSize,
      search: params.search,
      ownerId: params.ownerId,
      // A column the API refuses to sort by would answer 400 on a hand-edited link.
      sortBy: isContactSortField(params.sortBy) ? params.sortBy : 'createdAt',
      sortOrder: params.sortOrder ?? 'desc',
    }),
    [params],
  );

  const { data: page, isLoading } = useContactsList(query);
  const deleteContact = useDeleteContact();
  const { reportSuccess, reportFailure } = useMutationFeedback();

  const onDelete = useCallback(
    (id: Id) => {
      deleteContact.mutate(id, {
        onSuccess: () => reportSuccess('Контакт видалено'),
        onError: reportFailure,
      });
    },
    [deleteContact, reportSuccess, reportFailure],
  );

  const columns = useContactsTableColumns({ onDelete, isDeleting: deleteContact.isPending });
  const { filters } = useContactsTableFilters({ params, setParams, resetParams });

  const createButton = (
    <PermissionGate resource="contacts" action="write" fallback={null}>
      <Link href="/contacts/new">
        <Button type="primary" icon={<Plus size={16} />}>
          Новий контакт
        </Button>
      </Link>
    </PermissionGate>
  );

  const isFiltered = hasActiveContactFilters(params);
  // An untouched list with nothing in it invites the first record; a filtered
  // one that came back empty is a different message entirely.
  const isUntouchedAndEmpty = !isLoading && page !== undefined && page.total === 0 && !isFiltered;

  return (
    <>
      <PageHeader
        title="Контакти"
        description="Люди та компанії, з якими ви працюєте"
        actions={createButton}
      />

      {isUntouchedAndEmpty ? (
        <Card>
          <EmptyState description="Контактів ще немає" action={createButton} />
        </Card>
      ) : (
        <DataTable<Contact, ContactFilter>
          tableId="contacts"
          columns={columns}
          page={page}
          isLoading={isLoading}
          params={params}
          onParamsChange={setParams}
          onRowClick={(row) => router.push(`/contacts/${row.id}`)}
          filters={filters}
          emptyText="За цим запитом контактів не знайдено"
        />
      )}
    </>
  );
}

export default function ContactsPage() {
  return (
    <PermissionGate resource="contacts" action="read">
      <ContactsList />
    </PermissionGate>
  );
}
