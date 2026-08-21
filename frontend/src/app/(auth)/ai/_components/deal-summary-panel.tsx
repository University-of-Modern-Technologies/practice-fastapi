'use client';

import { Alert, Button, Card, Form, Input, Select, Skeleton, Typography } from 'antd';
import { useState } from 'react';
import { ReferenceSelect, applyServerErrors, zodRule } from '@/components';
import { dealLabel, useDealOptions, useResolvedDeal } from '@/app/(auth)/deals/deals.queries';
import type { Deal } from '@/app/(auth)/deals/deals.types';
import { DEAL_STAGE, DEAL_STAGES } from '@/shared/constants';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import type { IsoDateTime } from '@/types/domain';
import { useSummariseDeal } from '../ai.queries';
import { isModuleUnavailable } from '../ai.service';
import type { DealSummary, DealSummaryInput } from '../ai.types';
import {
  dealIdSchema,
  dealNotesSchema,
  dealStageSchema,
  dealTitleSchema,
  AI_MAX_INPUT_CHARS,
  type DealSummaryFormValues,
} from '../ai.validation';
import { ResultCard } from './result-card';

interface DealSummaryPanelProps {
  /** Called once the API build turns out not to serve the assistant at all. */
  readonly onUnavailable: () => void;
}

interface Answer {
  readonly data: DealSummary;
  readonly receivedAt: IsoDateTime;
}

/**
 * Asks the assistant for a short summary of one deal. The panel is independent
 * of its neighbour: a failure here leaves the classifier usable.
 */
export function DealSummaryPanel({ onUnavailable }: DealSummaryPanelProps) {
  const [form] = Form.useForm<DealSummaryFormValues>();
  const [selected, setSelected] = useState<Deal | undefined>(undefined);
  const [answer, setAnswer] = useState<Answer | undefined>(undefined);
  const { reportFailure } = useMutationFeedback();
  const summarise = useSummariseDeal();

  // Without `deals:read` there is no list to pick from, so the deal is described
  // by hand — the route needs a title and a stage, not only an identifier.
  const canReadDeals = useHasPermission('deals', 'read');

  const pick = (deal: Deal | undefined): void => {
    setSelected(deal);
    if (deal) form.setFieldsValue({ title: deal.title, stage: deal.stage });
  };

  /**
   * Built from the picked deal when there is one: the fields the contract
   * allows are read from the record, so what is sent matches what is stored.
   */
  const toInput = (values: DealSummaryFormValues): DealSummaryInput =>
    selected && selected.id === values.dealId
      ? {
          id: selected.id,
          title: selected.title,
          stage: selected.stage,
          amount: selected.amount,
          currency: selected.currency,
          probability: selected.probability,
          ...(selected.expectedCloseDate ? { expectedCloseDate: selected.expectedCloseDate } : {}),
          ...(values.notes ? { notes: values.notes } : {}),
        }
      : {
          id: values.dealId,
          title: values.title,
          stage: values.stage,
          ...(values.notes ? { notes: values.notes } : {}),
        };

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        summarise.mutate(toInput(values), {
          onSuccess: (data) => setAnswer({ data, receivedAt: new Date().toISOString() }),
          onError: (error) => {
            // A build without the assistant is an answer about the section, not
            // a failure of this request: it is never notified about.
            if (isModuleUnavailable(error)) {
              onUnavailable();
              return;
            }
            if (applyServerErrors(form, error)) return;
            reportFailure(error);
          },
        });
      })
      .catch(() => undefined);
  };

  return (
    <Card
      title="Резюме угоди"
      extra={
        <Button type="primary" loading={summarise.isPending} onClick={submit}>
          Скласти резюме
        </Button>
      }
    >
      <Form<DealSummaryFormValues> form={form} layout="vertical" disabled={summarise.isPending}>
        {canReadDeals ? (
          // The picker is mounted only where `deals:read` is granted: the hook
          // behind it must not fire a request the API would answer with 403.
          <Form.Item name="dealId" label="Угода" rules={[zodRule(dealIdSchema)]}>
            <ReferenceSelect
              useOptions={useDealOptions}
              useResolved={useResolvedDeal}
              getLabel={dealLabel}
              placeholder="Почніть вводити назву угоди"
              notFoundText="Угод не знайдено"
              onSelectRow={pick}
            />
          </Form.Item>
        ) : (
          <Form.Item
            name="dealId"
            label="Ідентифікатор угоди"
            extra="Ваша роль не дає доступу до списку угод, тому дані вводяться вручну."
            rules={[zodRule(dealIdSchema)]}
          >
            <Input placeholder="00000000-0000-0000-0000-000000000000" />
          </Form.Item>
        )}

        <Form.Item name="title" label="Назва угоди" rules={[zodRule(dealTitleSchema)]}>
          <Input placeholder="Назва, яку побачить модель" disabled={selected !== undefined} />
        </Form.Item>

        <Form.Item name="stage" label="Етап" rules={[zodRule(dealStageSchema)]}>
          <Select
            placeholder="Оберіть етап"
            disabled={selected !== undefined}
            options={DEAL_STAGES.map((stage) => ({ value: stage, label: DEAL_STAGE[stage].label }))}
          />
        </Form.Item>

        <Form.Item
          name="notes"
          label="Додатковий контекст"
          rules={[zodRule(dealNotesSchema)]}
          extra="Необовʼязково. Надсилається моделі разом з угодою."
        >
          <Input.TextArea
            rows={3}
            showCount
            maxLength={AI_MAX_INPUT_CHARS}
            placeholder="Домовленості, заперечення клієнта, наступні кроки"
          />
        </Form.Item>
      </Form>

      {summarise.isPending ? (
        <Card size="small">
          <Skeleton active paragraph={{ rows: 3 }} title={false} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Модель формує відповідь — це помітно довше за звичайний запит.
          </Typography.Text>
        </Card>
      ) : null}

      {!summarise.isPending && answer ? (
        <ResultCard
          title="Резюме"
          provider={answer.data.provider}
          cached={answer.data.cached}
          receivedAt={answer.receivedAt}
        >
          <Typography.Paragraph
            copyable={{ text: answer.data.summary }}
            style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}
          >
            {answer.data.summary}
          </Typography.Paragraph>
        </ResultCard>
      ) : null}

      {!summarise.isPending && !answer ? (
        <Alert
          type="info"
          showIcon
          message="Резюме складається на вимогу"
          description="Оберіть угоду й натисніть «Скласти резюме». Відповідь моделі — допоміжний текст, перевіряйте його перед надсиланням клієнту."
        />
      ) : null}
    </Card>
  );
}
