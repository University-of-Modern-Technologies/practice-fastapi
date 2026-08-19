'use client';

import { Alert, Button, Card, Form, Input, Skeleton, Space, Typography } from 'antd';
import { useState } from 'react';
import { StatusTag, applyServerErrors, zodRule } from '@/components';
import { formatRate } from '@/lib/number';
import { INQUIRY_CATEGORY } from '@/shared/constants';
import { useMutationFeedback } from '@/shared/hooks';
import type { IsoDateTime } from '@/types/domain';
import { useClassifyInquiry } from '../ai.queries';
import { isModuleUnavailable } from '../ai.service';
import { UNKNOWN_CATEGORY, type InquiryClassification } from '../ai.types';
import { AI_MAX_INPUT_CHARS, inquiryTextSchema, type InquiryFormValues } from '../ai.validation';
import { ResultCard } from './result-card';

interface InquiryClassifierPanelProps {
  readonly onUnavailable: () => void;
}

interface Answer {
  readonly data: InquiryClassification;
  readonly receivedAt: IsoDateTime;
}

/**
 * Sorts a free-text inquiry into one of the categories the API recognises. The
 * panel stands on its own: a failure here leaves the summary panel usable.
 */
export function InquiryClassifierPanel({ onUnavailable }: InquiryClassifierPanelProps) {
  const [form] = Form.useForm<InquiryFormValues>();
  const [answer, setAnswer] = useState<Answer | undefined>(undefined);
  const { reportFailure } = useMutationFeedback();
  const classify = useClassifyInquiry();

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => {
        classify.mutate(
          { text: values.text },
          {
            onSuccess: (data) => setAnswer({ data, receivedAt: new Date().toISOString() }),
            onError: (error) => {
              if (isModuleUnavailable(error)) {
                onUnavailable();
                return;
              }
              if (applyServerErrors(form, error)) return;
              reportFailure(error);
            },
          },
        );
      })
      .catch(() => undefined);
  };

  // `unknown` is what the server answers when the model replied with something
  // outside the closed list. It is a result the user can act on — check the
  // text by hand — and is deliberately not dressed as a failure.
  const isUnknown = answer?.data.category === UNKNOWN_CATEGORY;

  return (
    <Card
      title="Класифікація звернення"
      extra={
        <Button type="primary" loading={classify.isPending} onClick={submit}>
          Визначити категорію
        </Button>
      }
    >
      <Form<InquiryFormValues> form={form} layout="vertical" disabled={classify.isPending}>
        <Form.Item name="text" label="Текст звернення" rules={[zodRule(inquiryTextSchema)]}>
          <Input.TextArea
            rows={8}
            showCount
            maxLength={AI_MAX_INPUT_CHARS}
            placeholder="Вставте лист або повідомлення клієнта"
          />
        </Form.Item>
      </Form>

      {classify.isPending ? (
        <Card size="small">
          <Skeleton active paragraph={{ rows: 1 }} title={false} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Модель формує відповідь — це помітно довше за звичайний запит.
          </Typography.Text>
        </Card>
      ) : null}

      {!classify.isPending && answer ? (
        <ResultCard
          title="Категорія"
          provider={answer.data.provider}
          cached={answer.data.cached}
          receivedAt={answer.receivedAt}
        >
          <Space size="middle" wrap>
            <StatusTag dictionary={INQUIRY_CATEGORY} value={answer.data.category} />
            <Typography.Text type="secondary">
              {`Впевненість: ${formatRate(answer.data.confidence)}`}
            </Typography.Text>
          </Space>

          {isUnknown ? (
            <Alert
              type="warning"
              showIcon
              message="Не вдалося впевнено визначити категорію"
              description="Модель відповіла значенням поза закритим переліком категорій, тому відповідь не зараховано. Перегляньте звернення вручну або надішліть коротший, конкретніший фрагмент тексту."
            />
          ) : null}
        </ResultCard>
      ) : null}

      {!classify.isPending && !answer ? (
        <Alert
          type="info"
          showIcon
          message="Категорія визначається на вимогу"
          description="Вставте текст звернення й натисніть «Визначити категорію». Результат — підказка для маршрутизації, остаточне рішення лишається за оператором."
        />
      ) : null}
    </Card>
  );
}
