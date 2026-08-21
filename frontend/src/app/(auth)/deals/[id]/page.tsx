'use client';

import { Alert, Button, Card, Descriptions, Form, Space, Typography } from 'antd';
import { Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import {
  BackButton,
  CopyableValue,
  DateValue,
  DeleteConfirm,
  EmptyState,
  FormCard,
  FormPageSkeleton,
  MoneyValue,
  PageHeader,
  PermissionGate,
  StatusTag,
} from '@/components';
import { ApiError } from '@/shared/api';
import { DEAL_STAGE, DEAL_STAGE_TRANSITIONS, statusMeta, type DealStage } from '@/shared/constants';
import { useMutationFeedback } from '@/shared/hooks';
import { StageTransitionModal } from '../_components';
import { useDealForm } from '../_hooks';
import { useDeal, useDeleteDeal, useTransitionDeal } from '../deals.queries';
import {
  DEAL_ERROR,
  asTransitionDetails,
  type Deal,
  type DealTransitionDetails,
} from '../deals.types';
import type { DealFormValues } from '../deals.validation';

const Meta = ({ deal }: { readonly deal: Deal }) => (
  <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} bordered>
    <Descriptions.Item label="Ідентифікатор">
      <CopyableValue value={deal.id} />
    </Descriptions.Item>
    <Descriptions.Item label="Сума">
      <MoneyValue value={deal.amount} currency={deal.currency} showCurrency />
    </Descriptions.Item>
    <Descriptions.Item label="Ймовірність">
      <span className="numeric">{deal.probability} %</span>
    </Descriptions.Item>
    <Descriptions.Item label="Очікуване закриття">
      <DateValue value={deal.expectedCloseDate} />
    </Descriptions.Item>
    <Descriptions.Item label="Закрито">
      <DateValue value={deal.closedAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Створено">
      <DateValue value={deal.createdAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Оновлено">
      <DateValue value={deal.updatedAt} withTime />
    </Descriptions.Item>
  </Descriptions>
);

/** Names the stages a refused move would have been allowed to reach. */
const allowedStages = (details: DealTransitionDetails): string =>
  details.allowed.map((stage) => statusMeta(DEAL_STAGE, stage).label).join(', ');

export default function DealPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { reportSuccess } = useMutationFeedback();

  const [target, setTarget] = useState<DealStage | null>(null);
  const [refused, setRefused] = useState<DealTransitionDetails | null>(null);

  const { data: deal, isLoading, isError, isFetching, refetch } = useDeal(id);
  const remove = useDeleteDeal(id);
  const transition = useTransitionDeal(id);

  const { formProps, fields, conflictAlert, submit, isSaving, handleError } = useDealForm({
    deal,
    // The card stays put after a save: the fresh version arrives through the
    // cache, so there is nowhere to navigate.
    onSaved: () => undefined,
    onReload: refetch,
    isReloading: isFetching,
  });

  if (isLoading) return <FormPageSkeleton />;
  if (isError || deal === undefined) return <EmptyState description="Угоду не знайдено" />;

  const nextStages = DEAL_STAGE_TRANSITIONS[deal.stage];

  /**
   * A refused transition and a lost race share the 409, so the code decides
   * which of the two the page explains — the stage machine has its own answer
   * and its own list of moves that were open.
   */
  const onTransitionError = (error: unknown): void => {
    if (error instanceof ApiError && error.code === DEAL_ERROR.transition) {
      setRefused(asTransitionDetails(error.details) ?? { from: deal.stage, to: '', allowed: [] });
      setTarget(null);
      return;
    }
    handleError(error);
  };

  const onTransition = (probability: number): void => {
    if (target === null) return;
    setRefused(null);

    transition.mutate(
      // The version the card read: the stage moves only from the state the
      // operator was looking at.
      { version: deal.version, stage: target, probability },
      {
        onSuccess: () => {
          reportSuccess('Стадію змінено');
          setTarget(null);
        },
        onError: onTransitionError,
      },
    );
  };

  const onDelete = () => {
    // The same version the form holds: a delete can lose the race just as a save can.
    remove.mutate(deal.version, {
      onSuccess: () => {
        reportSuccess('Угоду видалено');
        router.replace('/deals');
      },
      onError: handleError,
    });
  };

  const deleteAction = (
    <PermissionGate resource="deals" action="delete" fallback={null}>
      <DeleteConfirm
        onConfirm={onDelete}
        isPending={remove.isPending}
        title="Видалити угоду?"
        description="Угоду буде приховано зі списку."
      >
        <Button danger icon={<Trash2 size={16} />} loading={remove.isPending}>
          Видалити
        </Button>
      </DeleteConfirm>
    </PermissionGate>
  );

  return (
    <PermissionGate resource="deals" action="read">
      <PageHeader
        title={deal.title}
        description="Картка угоди"
        actions={<StatusTag dictionary={DEAL_STAGE} value={deal.stage} />}
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
              ? `З поточної стадії дозволено перейти до: ${allowedStages(refused)}. Перечитайте угоду — її стадію змінив хтось інший.`
              : 'Угоду вже закрито, подальші переходи недоступні. Перечитайте угоду.'
          }
          onClose={() => setRefused(null)}
        />
      ) : null}

      <div className="mb-4">
        <Meta deal={deal} />
      </div>

      <Card
        title="Стадія"
        className="mb-4"
        // The moves come from the state machine, so a step the API forbids is
        // never offered; its 409 stays a safety net rather than the first check.
        extra={<StatusTag dictionary={DEAL_STAGE} value={deal.stage} />}
      >
        {nextStages.length === 0 ? (
          <Typography.Text type="secondary">Угоду закрито</Typography.Text>
        ) : (
          <PermissionGate
            resource="deals"
            action="write"
            fallback={
              <Typography.Text type="secondary">Немає прав на зміну стадії</Typography.Text>
            }
          >
            <Space wrap>
              {nextStages.map((stage) => (
                <Button
                  key={stage}
                  onClick={() => setTarget(stage)}
                  loading={transition.isPending && target === stage}
                >
                  {DEAL_STAGE[stage].label}
                </Button>
              ))}
            </Space>
          </PermissionGate>
        )}
      </Card>

      <StageTransitionModal
        target={target}
        currentProbability={deal.probability}
        isSaving={transition.isPending}
        onCancel={() => setTarget(null)}
        onSubmit={onTransition}
      />

      <PermissionGate
        resource="deals"
        action="write"
        fallback={
          <Card
            title="Дані угоди"
            extra={
              <>
                {deleteAction}
                <BackButton href="/deals" />
              </>
            }
          >
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Контакт">{deal.contactId ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="Валюта">{deal.currency}</Descriptions.Item>
            </Descriptions>
          </Card>
        }
      >
        <Form<DealFormValues> {...formProps}>
          <FormCard
            title="Дані угоди"
            isSaving={isSaving}
            onSubmit={submit}
            extra={deleteAction}
            backHref="/deals"
          >
            {fields}
          </FormCard>
        </Form>
      </PermissionGate>
    </PermissionGate>
  );
}
