'use client';

import { Button, Card, Space, Typography } from 'antd';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { PermissionGate } from '@/components';
import { useHasPermission } from '@/shared/hooks';
import { useResolvedContact, contactLabel } from '../../contacts/contacts.queries';
import { dealLabel, useResolvedDeal } from '../../deals/deals.queries';
import { useResolvedUser, userLabel } from '../../users/users.queries';
import type { Call } from '../calls.types';

interface CallLinksProps {
  readonly call: Call;
  /** The link action, when the viewer may perform it. */
  readonly action?: ReactNode;
  /**
   * Detaching is a different request from attaching — a PATCH clearing the
   * field, not the link action — so it is offered as its own control next to
   * the reference it removes.
   */
  readonly onUnlinkContact: () => void;
  readonly onUnlinkDeal: () => void;
  readonly isUnlinking: boolean;
}

/**
 * What a call has been attributed to — and, just as often, what it has not.
 *
 * A call arrives from the provider before anyone has decided whose it is or
 * what it was about, so all three references being empty is the ordinary state
 * of a fresh record. That is why nothing here is drawn as a missing value: an
 * empty slot says what has not happened yet, in a full sentence, rather than
 * leaving a dash that reads as data the system lost.
 */
function Slot({
  label,
  href,
  name,
  pending,
  unresolved,
  onUnlink,
  isUnlinking,
}: {
  readonly label: string;
  readonly href: string | null;
  readonly name: string | null;
  /** Wording for "nobody has done this yet" — not an error. */
  readonly pending: string;
  /** The reference is set, but this viewer may not read the record behind it. */
  readonly unresolved: string;
  /** Absent on the owner, which is changed through the form rather than here. */
  readonly onUnlink?: (() => void) | undefined;
  readonly isUnlinking?: boolean | undefined;
}) {
  return (
    <div className="mb-3">
      <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
        {label}
      </Typography.Text>

      {href === null ? (
        <Typography.Text type="secondary" italic>
          {pending}
        </Typography.Text>
      ) : (
        <Space size="small">
          <Link href={href}>{name ?? unresolved}</Link>

          {onUnlink ? (
            <PermissionGate resource="calls" action="write" fallback={null}>
              <Button type="link" size="small" loading={isUnlinking ?? false} onClick={onUnlink}>
                Відвʼязати
              </Button>
            </PermissionGate>
          ) : null}
        </Space>
      )}
    </div>
  );
}

export function CallLinks({
  call,
  action,
  onUnlinkContact,
  onUnlinkDeal,
  isUnlinking,
}: CallLinksProps) {
  // The reference is only resolved when the viewer may read that directory:
  // passing `undefined` keeps the hook in place while its request stays unsent.
  const canReadContacts = useHasPermission('contacts', 'read');
  const canReadDeals = useHasPermission('deals', 'read');
  const canReadUsers = useHasPermission('users', 'read');

  const contact = useResolvedContact(
    canReadContacts && call.contactId !== null ? call.contactId : undefined,
  );
  const deal = useResolvedDeal(canReadDeals && call.dealId !== null ? call.dealId : undefined);
  const owner = useResolvedUser(canReadUsers && call.ownerId !== null ? call.ownerId : undefined);

  return (
    <Card title="Звʼязки" className="mb-4" {...(action ? { extra: action } : {})}>
      <Slot
        label="Контакт"
        href={call.contactId === null ? null : `/contacts/${call.contactId}`}
        name={contact ? contactLabel(contact) : null}
        pending="Ще не привʼязано до контакту"
        unresolved="Контакт недоступний для читання"
        onUnlink={onUnlinkContact}
        isUnlinking={isUnlinking}
      />

      <Slot
        label="Угода"
        href={call.dealId === null ? null : `/deals/${call.dealId}`}
        name={deal ? dealLabel(deal) : null}
        pending="Ще не привʼязано до угоди"
        unresolved="Угода недоступна для читання"
        onUnlink={onUnlinkDeal}
        isUnlinking={isUnlinking}
      />

      <Slot
        label="Відповідальний"
        href={call.ownerId === null ? null : `/users/${call.ownerId}`}
        name={owner ? userLabel(owner) : null}
        pending="Дзвінок ще ніхто не взяв"
        unresolved="Обліковий запис недоступний для читання"
      />
    </Card>
  );
}
