'use client';

import { Button, Space } from 'antd';
import Link from 'next/link';
import { Pencil, Trash2 } from 'lucide-react';
import { useMemo } from 'react';
import {
  CopyableValue,
  DateValue,
  DeleteConfirm,
  PermissionGate,
  ShowMoreText,
  type DataTableColumns,
} from '@/components';
import type { Id } from '@/types/domain';
import type { Contact } from '../contacts.types';

interface UseContactsTableColumnsOptions {
  readonly onDelete: (id: Id) => void;
  readonly isDeleting: boolean;
}

/**
 * Column keys match the `sortBy` values the API accepts, which is what lets the
 * table hand its header clicks straight to the query string.
 */
export const useContactsTableColumns = ({
  onDelete,
  isDeleting,
}: UseContactsTableColumnsOptions): DataTableColumns<Contact> =>
  useMemo(
    () => [
      {
        key: 'lastName',
        dataIndex: 'lastName',
        title: 'Прізвище',
        sorter: true,
        width: 160,
      },
      {
        key: 'firstName',
        dataIndex: 'firstName',
        title: 'Імʼя',
        sorter: true,
        width: 140,
      },
      {
        key: 'company',
        dataIndex: 'company',
        title: 'Компанія',
        sorter: true,
        width: 180,
        render: (company: string | null) => company ?? '—',
      },
      {
        key: 'email',
        dataIndex: 'email',
        title: 'Пошта',
        width: 220,
        render: (email: string | null) => <CopyableValue value={email} mono={false} />,
      },
      {
        key: 'phone',
        dataIndex: 'phone',
        title: 'Телефон',
        width: 170,
        render: (phone: string | null) => <CopyableValue value={phone} />,
      },
      {
        key: 'notes',
        dataIndex: 'notes',
        title: 'Нотатки',
        width: 240,
        render: (notes: string | null) => <ShowMoreText text={notes} limit={60} />,
      },
      {
        key: 'createdAt',
        dataIndex: 'createdAt',
        title: 'Створено',
        sorter: true,
        width: 130,
        render: (createdAt: string) => <DateValue value={createdAt} />,
      },
      {
        key: 'actions',
        title: '',
        width: 92,
        fixed: 'right' as const,
        render: (_value: unknown, row: Contact) => (
          // Stops the row's own navigation from firing under the buttons.
          <Space size={4} onClick={(event) => event.stopPropagation()}>
            <PermissionGate resource="contacts" action="write" fallback={null}>
              <Link href={`/contacts/${row.id}`}>
                <Button type="text" size="small" icon={<Pencil size={15} />} title="Редагувати" />
              </Link>
            </PermissionGate>
            <PermissionGate resource="contacts" action="delete" fallback={null}>
              <DeleteConfirm
                title="Видалити контакт?"
                description={`${row.lastName} ${row.firstName} зникне зі списку.`}
                isPending={isDeleting}
                onConfirm={() => onDelete(row.id)}
              >
                <Button type="text" size="small" danger icon={<Trash2 size={15} />} />
              </DeleteConfirm>
            </PermissionGate>
          </Space>
        ),
      },
    ],
    [onDelete, isDeleting],
  );
