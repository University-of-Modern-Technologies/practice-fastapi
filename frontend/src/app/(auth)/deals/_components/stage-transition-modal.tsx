'use client';

import { Alert, Form, InputNumber, Typography } from 'antd';
import { useEffect } from 'react';
import { FormModal, StatusTag, zodRule } from '@/components';
import { DEAL_STAGE, DEAL_STAGE_PROBABILITY, type DealStage } from '@/shared/constants';
import {
  CERTAIN_PROBABILITY,
  dealProbabilitySchema,
  type DealTransitionFormValues,
} from '../deals.validation';

interface StageTransitionModalProps {
  /** The stage being moved to; nothing is shown until a button picks one. */
  readonly target: DealStage | null;
  readonly currentProbability: number;
  readonly isSaving: boolean;
  readonly onCancel: () => void;
  readonly onSubmit: (probability: number) => void;
}

/** A terminal stage fixes the odds; anything else may not claim certainty. */
const freeProbabilitySchema = dealProbabilitySchema.refine(
  (value) => value !== CERTAIN_PROBABILITY,
  { message: 'Ймовірність 100 % можлива лише для виграної угоди' },
);

/**
 * Confirms a move along the stage machine. The stage itself is not chosen here
 * — the caller offers only the moves the machine allows — so the dialog asks
 * for the one value that travels with it.
 */
export function StageTransitionModal({
  target,
  currentProbability,
  isSaving,
  onCancel,
  onSubmit,
}: StageTransitionModalProps) {
  const [form] = Form.useForm<DealTransitionFormValues>();

  const fixed = target === null ? null : DEAL_STAGE_PROBABILITY[target];
  const suggested =
    fixed ??
    (currentProbability === CERTAIN_PROBABILITY ? CERTAIN_PROBABILITY - 1 : currentProbability);

  // The dialog is mounted once and reused, so the field is refilled whenever a
  // different move is picked; without this it would keep the previous answer.
  useEffect(() => {
    if (target !== null) form.setFieldsValue({ probability: suggested });
  }, [form, target, suggested]);

  const submit = (): void => {
    void form
      .validateFields()
      .then((values) => onSubmit(fixed ?? values.probability))
      // A field that failed its own rule already shows why.
      .catch(() => undefined);
  };

  return (
    <FormModal
      open={target !== null}
      title="Змінити стадію"
      isSaving={isSaving}
      onSubmit={submit}
      onCancel={onCancel}
      submitLabel="Перевести"
      width={480}
    >
      {target === null ? null : (
        <>
          <Typography.Paragraph>
            Нова стадія: <StatusTag dictionary={DEAL_STAGE} value={target} />
          </Typography.Paragraph>

          {fixed === null ? (
            <Alert
              type="info"
              showIcon
              className="mb-4"
              message="Ймовірність 100 % доступна лише для виграної угоди"
            />
          ) : (
            <Alert
              type="info"
              showIcon
              className="mb-4"
              message={`Для цієї стадії ймовірність фіксована: ${fixed} %`}
            />
          )}

          <Form<DealTransitionFormValues>
            form={form}
            layout="vertical"
            requiredMark={false}
            initialValues={{ probability: suggested }}
          >
            <Form.Item
              name="probability"
              label="Ймовірність, %"
              rules={[zodRule(fixed === null ? freeProbabilitySchema : dealProbabilitySchema)]}
            >
              <InputNumber
                min={0}
                max={100}
                step={5}
                style={{ width: '100%' }}
                // The value is not the operator's to choose here: the API
                // accepts exactly one number for a terminal stage.
                disabled={fixed !== null}
              />
            </Form.Item>
          </Form>
        </>
      )}
    </FormModal>
  );
}
