'use client';

import { Button, Card, Descriptions, Form, Result, Space, Typography } from 'antd';
import { Link2, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import {
  BackButton,
  CopyableValue,
  DateValue,
  DeleteConfirm,
  FormCard,
  FormPageSkeleton,
  PageHeader,
  PermissionGate,
  ShowMoreText,
  StatusTag,
} from '@/components';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { CallDuration, CallLinks, CallRecordingCard, LinkCallModal } from '../_components';
import { useCallForm } from '../_hooks';
import { useCall, useDeleteCall, useUpdateCall } from '../calls.queries';
import { type Call } from '../calls.types';
import { CALL_DIRECTION, CALL_DISPOSITION } from '@/shared/constants';
import type { CallFormValues } from '../calls.validation';

const Meta = ({ call }: { readonly call: Call }) => (
  <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} bordered>
    <Descriptions.Item label="Ідентифікатор у провайдера">
      <CopyableValue value={call.externalId} />
    </Descriptions.Item>
    <Descriptions.Item label="Ідентифікатор">
      <CopyableValue value={call.id} />
    </Descriptions.Item>
    <Descriptions.Item label="Напрямок">
      <StatusTag dictionary={CALL_DIRECTION} value={call.direction} />
    </Descriptions.Item>
    <Descriptions.Item label="Результат">
      <StatusTag dictionary={CALL_DISPOSITION} value={call.disposition} />
    </Descriptions.Item>
    <Descriptions.Item label="Звідки">
      <span className="numeric">{call.fromNumber}</span>
    </Descriptions.Item>
    <Descriptions.Item label="Куди">
      <span className="numeric">{call.toNumber}</span>
    </Descriptions.Item>
    <Descriptions.Item label="Початок">
      <DateValue value={call.startedAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Тривалість">
      <CallDuration seconds={call.durationSeconds} />
    </Descriptions.Item>
    <Descriptions.Item label="Створено">
      <DateValue value={call.createdAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Оновлено">
      <DateValue value={call.updatedAt} withTime />
    </Descriptions.Item>
  </Descriptions>
);

/**
 * The card of a loaded call. It is its own component so the form hook can take
 * the record itself rather than "the record, or nothing yet" — the create route
 * that would have justified the optional form does not exist here.
 */
function CallCard({
  call,
  onReload,
  isReloading,
}: {
  readonly call: Call;
  readonly onReload: () => unknown;
  readonly isReloading: boolean;
}) {
  const router = useRouter();
  const { reportSuccess } = useMutationFeedback();

  const [isLinking, setIsLinking] = useState(false);

  const remove = useDeleteCall(call.id);
  // Detaching is a PATCH that clears the field: the link action only ever
  // attaches, and it refuses a `null` outright.
  const detach = useUpdateCall(call.id);

  const { formProps, fields, conflictAlert, submit, isSaving, handleError } = useCallForm({
    call,
    // The card stays put after a save: the fresh version arrives through the
    // cache, so there is nowhere to navigate.
    onSaved: () => undefined,
    onReload,
    isReloading,
  });

  /**
   * The link action can lose the same race a save can, and when it does the
   * answer belongs in the one conflict alert this card already shows rather
   * than in a second one of the dialog's own.
   */
  const handleLinkConflict = (error: unknown): boolean => {
    if (!(error instanceof ApiError) || !error.isConflict) return false;
    handleError(error);
    return true;
  };

  const unlinkContact = () => {
    detach.mutate(
      { version: call.version, contactId: null },
      { onSuccess: () => reportSuccess('Контакт відвʼязано'), onError: handleError },
    );
  };

  const unlinkDeal = () => {
    detach.mutate(
      { version: call.version, dealId: null },
      { onSuccess: () => reportSuccess('Угоду відвʼязано'), onError: handleError },
    );
  };

  const onDelete = () => {
    // The same version the form holds: a delete can lose the race just as a save can.
    remove.mutate(call.version, {
      onSuccess: () => {
        reportSuccess('Дзвінок видалено');
        router.replace('/calls');
      },
      onError: handleError,
    });
  };

  const deleteAction = (
    <PermissionGate resource="calls" action="delete" fallback={null}>
      <DeleteConfirm
        onConfirm={onDelete}
        isPending={remove.isPending}
        title="Видалити дзвінок?"
        description="Дзвінок буде приховано з журналу."
      >
        <Button danger icon={<Trash2 size={16} />} loading={remove.isPending}>
          Видалити
        </Button>
      </DeleteConfirm>
    </PermissionGate>
  );

  const linkAction = (
    <PermissionGate resource="calls" action="write" fallback={null}>
      <Button icon={<Link2 size={16} />} onClick={() => setIsLinking(true)}>
        {call.contactId === null && call.dealId === null ? 'Привʼязати' : 'Змінити привʼязку'}
      </Button>
    </PermissionGate>
  );

  return (
    <>
      <PageHeader
        title={`${call.fromNumber} → ${call.toNumber}`}
        description="Картка дзвінка"
        actions={
          <Space wrap>
            <StatusTag dictionary={CALL_DIRECTION} value={call.direction} />
            <StatusTag dictionary={CALL_DISPOSITION} value={call.disposition} />
          </Space>
        }
      />

      {conflictAlert}

      <div className="mb-4">
        <Meta call={call} />
      </div>

      <CallLinks
        call={call}
        action={linkAction}
        onUnlinkContact={unlinkContact}
        onUnlinkDeal={unlinkDeal}
        isUnlinking={detach.isPending}
      />

      <LinkCallModal
        call={isLinking ? call : null}
        onCancel={() => setIsLinking(false)}
        onLinked={() => setIsLinking(false)}
        onConflict={handleLinkConflict}
      />

      <CallRecordingCard call={call} />

      <PermissionGate
        resource="calls"
        action="write"
        fallback={
          <Card
            title="Нотатки"
            extra={
              <>
                {deleteAction}
                <BackButton href="/calls" />
              </>
            }
          >
            {call.notes === null ? (
              <Typography.Text type="secondary" italic>
                Нотаток до цього дзвінка ще немає
              </Typography.Text>
            ) : (
              <ShowMoreText text={call.notes} limit={400} />
            )}
          </Card>
        }
      >
        <Form<CallFormValues> {...formProps}>
          <FormCard
            title="Нотатки й відповідальний"
            isSaving={isSaving}
            onSubmit={submit}
            extra={deleteAction}
            backHref="/calls"
          >
            {fields}
          </FormCard>
        </Form>
      </PermissionGate>
    </>
  );
}

export default function CallPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: call, isLoading, isError, error, isFetching, refetch } = useCall(id);

  if (isLoading) return <FormPageSkeleton />;

  if (isError || call === undefined) {
    // A record someone else owns answers 404 rather than 403, so that the
    // endpoint cannot be used to find out which identifiers exist. The page
    // therefore names both readings instead of claiming the record is gone.
    const notFound = !(error instanceof ApiError) || error.status === 404;

    return (
      <Result
        status={notFound ? '404' : 'error'}
        title={notFound ? 'Дзвінок не знайдено' : 'Не вдалося прочитати дзвінок'}
        subTitle={
          notFound
            ? 'Запис міг бути видалений, або він недоступний вашій області доступу.'
            : 'Спробуйте ще раз або зверніться до адміністратора.'
        }
        extra={
          <Link href="/calls">
            <Button type="primary">До журналу</Button>
          </Link>
        }
      />
    );
  }

  return (
    <PermissionGate resource="calls" action="read">
      <CallCard call={call} onReload={refetch} isReloading={isFetching} />
    </PermissionGate>
  );
}
