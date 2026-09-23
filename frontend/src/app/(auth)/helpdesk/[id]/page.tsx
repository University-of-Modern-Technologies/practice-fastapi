'use client';

import { Alert, Button, Card, Descriptions, Form, Result, Space, Typography } from 'antd';
import { Trash2 } from 'lucide-react';
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
import { statusMeta } from '@/shared/constants';
import { useMutationFeedback } from '@/shared/hooks';
import { StatusTransitionModal } from '../_components';
import { useTicketForm } from '../_hooks';
import { useDeleteTicket, useTicket, useTransitionTicket } from '../helpdesk.queries';
import {
  TICKET_ERROR,
  asTransitionDetails,
  type Ticket,
  type TicketTransitionDetails,
} from '../helpdesk.types';
import {
  TICKET_CHANNEL,
  TICKET_PRIORITY,
  TICKET_STATUS,
  TICKET_STATUS_TRANSITIONS,
  type TicketStatus,
} from '@/shared/constants';
import type { TicketFormValues } from '../helpdesk.validation';

const Meta = ({ ticket }: { readonly ticket: Ticket }) => (
  <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} bordered>
    <Descriptions.Item label="Номер">
      <CopyableValue value={ticket.number} />
    </Descriptions.Item>
    <Descriptions.Item label="Ідентифікатор">
      <CopyableValue value={ticket.id} />
    </Descriptions.Item>
    <Descriptions.Item label="Канал">
      <StatusTag dictionary={TICKET_CHANNEL} value={ticket.channel} />
    </Descriptions.Item>
    <Descriptions.Item label="Пріоритет">
      <StatusTag dictionary={TICKET_PRIORITY} value={ticket.priority} />
    </Descriptions.Item>
    <Descriptions.Item label="Відкрито">
      <DateValue value={ticket.openedAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Розвʼязано">
      <DateValue value={ticket.resolvedAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Створено">
      <DateValue value={ticket.createdAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Оновлено">
      <DateValue value={ticket.updatedAt} withTime />
    </Descriptions.Item>
  </Descriptions>
);

/** Names the states a refused move would have been allowed to reach. */
const allowedStatuses = (details: TicketTransitionDetails): string =>
  details.allowed.map((status) => statusMeta(TICKET_STATUS, status).label).join(', ');

export default function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { reportSuccess } = useMutationFeedback();

  const [target, setTarget] = useState<TicketStatus | null>(null);
  const [refused, setRefused] = useState<TicketTransitionDetails | null>(null);

  const { data: ticket, isLoading, isError, error, isFetching, refetch } = useTicket(id);
  const remove = useDeleteTicket(id);
  const transition = useTransitionTicket(id);

  const { formProps, fields, conflictAlert, submit, isSaving, handleError } = useTicketForm({
    ticket,
    // The card stays put after a save: the fresh version arrives through the
    // cache, so there is nowhere to navigate.
    onSaved: () => undefined,
    onReload: refetch,
    isReloading: isFetching,
  });

  if (isLoading) return <FormPageSkeleton />;

  if (isError || ticket === undefined) {
    // A record someone else owns answers 404 rather than 403, so that the
    // endpoint cannot be used to find out which identifiers exist. The page
    // therefore names both readings instead of claiming the record is gone.
    const notFound = !(error instanceof ApiError) || error.status === 404;

    return (
      <Result
        status={notFound ? '404' : 'error'}
        title={notFound ? 'Звернення не знайдено' : 'Не вдалося прочитати звернення'}
        subTitle={
          notFound
            ? 'Запис міг бути видалений, або він недоступний вашій області доступу.'
            : 'Спробуйте ще раз або зверніться до адміністратора.'
        }
        extra={
          <Link href="/helpdesk">
            <Button type="primary">До списку</Button>
          </Link>
        }
      />
    );
  }

  const nextStatuses = TICKET_STATUS_TRANSITIONS[ticket.status];

  /**
   * Two refusals can follow the same button. A lost race answers 409 and is
   * resolved by re-reading; a move the machine forbids answers 422 and
   * re-reading changes nothing, so the page names the moves that were open
   * instead of offering a reload.
   */
  const onTransitionError = (failure: unknown): void => {
    if (failure instanceof ApiError && failure.code === TICKET_ERROR.transition) {
      setRefused(
        asTransitionDetails(failure.details) ?? { from: ticket.status, to: '', allowed: [] },
      );
      setTarget(null);
      return;
    }
    handleError(failure);
  };

  const onTransition = (note: string | undefined): void => {
    if (target === null) return;
    setRefused(null);

    transition.mutate(
      // The version the card read: the state moves only from the one the
      // operator was looking at.
      { version: ticket.version, toStatus: target, ...(note === undefined ? {} : { note }) },
      {
        onSuccess: () => {
          reportSuccess('Стан звернення змінено');
          setTarget(null);
        },
        onError: onTransitionError,
      },
    );
  };

  const onDelete = () => {
    // The same version the form holds: a delete can lose the race just as a save can.
    remove.mutate(ticket.version, {
      onSuccess: () => {
        reportSuccess('Звернення видалено');
        router.replace('/helpdesk');
      },
      onError: handleError,
    });
  };

  const deleteAction = (
    <PermissionGate resource="helpdesk" action="delete" fallback={null}>
      <DeleteConfirm
        onConfirm={onDelete}
        isPending={remove.isPending}
        title="Видалити звернення?"
        description="Звернення буде приховано зі списку."
      >
        <Button danger icon={<Trash2 size={16} />} loading={remove.isPending}>
          Видалити
        </Button>
      </DeleteConfirm>
    </PermissionGate>
  );

  return (
    <PermissionGate resource="helpdesk" action="read">
      <PageHeader
        title={`${ticket.number} · ${ticket.subject}`}
        description="Картка звернення"
        actions={<StatusTag dictionary={TICKET_STATUS} value={ticket.status} />}
      />

      {conflictAlert}

      {refused ? (
        <Alert
          type="error"
          showIcon
          closable
          className="mb-4"
          message="Такий перехід неможливий"
          description={
            refused.allowed.length > 0
              ? `З поточного стану дозволено перейти до: ${allowedStatuses(refused)}. Перечитайте звернення — його стан змінив хтось інший.`
              : 'Звернення вже закрито, подальші переходи недоступні. Перечитайте звернення.'
          }
          onClose={() => setRefused(null)}
        />
      ) : null}

      <div className="mb-4">
        <Meta ticket={ticket} />
      </div>

      <Card
        title="Стан"
        className="mb-4"
        // The moves come from the state machine, so a step the API forbids is
        // never offered; its 422 stays a safety net rather than the first check.
        extra={<StatusTag dictionary={TICKET_STATUS} value={ticket.status} />}
      >
        {nextStatuses.length === 0 ? (
          <Typography.Text type="secondary">Звернення закрито</Typography.Text>
        ) : (
          <PermissionGate
            resource="helpdesk"
            action="write"
            fallback={<Typography.Text type="secondary">Немає прав на зміну стану</Typography.Text>}
          >
            <Space wrap>
              {nextStatuses.map((status) => (
                <Button
                  key={status}
                  onClick={() => setTarget(status)}
                  loading={transition.isPending && target === status}
                >
                  {TICKET_STATUS[status].label}
                </Button>
              ))}
            </Space>
          </PermissionGate>
        )}
      </Card>

      <StatusTransitionModal
        target={target}
        isSaving={transition.isPending}
        onCancel={() => setTarget(null)}
        onSubmit={onTransition}
      />

      <PermissionGate
        resource="helpdesk"
        action="write"
        fallback={
          <Card
            title="Дані звернення"
            extra={
              <>
                {deleteAction}
                <BackButton href="/helpdesk" />
              </>
            }
          >
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Тема">{ticket.subject}</Descriptions.Item>
              <Descriptions.Item label="Опис">
                <ShowMoreText text={ticket.body} limit={400} />
              </Descriptions.Item>
            </Descriptions>
          </Card>
        }
      >
        <Form<TicketFormValues> {...formProps}>
          <FormCard
            title="Дані звернення"
            isSaving={isSaving}
            onSubmit={submit}
            extra={deleteAction}
            backHref="/helpdesk"
          >
            {fields}
          </FormCard>
        </Form>
      </PermissionGate>
    </PermissionGate>
  );
}
