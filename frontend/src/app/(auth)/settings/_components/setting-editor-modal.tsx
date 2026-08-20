'use client';

import { Form, Input, Typography } from 'antd';
import { ApiError } from '@/shared/api';
import { useMutationFeedback } from '@/shared/hooks';
import { applyServerErrors, FormModal, requiredRule, zodRule } from '@/components';
import { useUpdateSetting } from '../settings.queries';
import { SETTING_ERROR, type Setting } from '../settings.types';
import { descriptionSchema, settingField, toFormValue, toWireValue } from '../settings.validation';

interface SettingEditorModalProps {
  /** The row being edited; `null` keeps the dialog closed. */
  readonly setting: Setting | null;
  readonly onClose: () => void;
}

interface SettingFormValues {
  readonly value: string;
  readonly description?: string;
}

export function SettingEditorModal({ setting, onClose }: SettingEditorModalProps) {
  const [form] = Form.useForm<SettingFormValues>();
  const { reportSuccess, reportFailure } = useMutationFeedback();
  const update = useUpdateSetting();

  const key = setting?.key ?? '';
  const field = settingField(key);

  const submit = () => {
    if (!setting) return;

    void form.validateFields().then((values) => {
      let wireValue: unknown;
      try {
        wireValue = toWireValue(setting.key, values.value);
      } catch {
        form.setFields([{ name: 'value', errors: ['Значення має бути коректним JSON'] }]);
        return;
      }

      const description = values.description?.trim() ?? '';

      update.mutate(
        {
          key: setting.key,
          input: {
            value: wireValue,
            // Sent only when the user actually wrote one: an empty string would
            // overwrite the registry description with nothing.
            ...(description ? { description } : {}),
          },
        },
        {
          onSuccess: () => {
            reportSuccess('Налаштування збережено');
            onClose();
          },
          onError: (error) => {
            const code = error instanceof ApiError ? error.code : null;

            // Both refusals are about this one field, so they belong on it —
            // a corner notification leaves the user guessing what to correct.
            if (code === SETTING_ERROR.invalidValue) {
              form.setFields([
                { name: 'value', errors: [`Значення не відповідає формату ключа. ${field.hint}`] },
              ]);
              return;
            }
            if (code === SETTING_ERROR.unknownKey) {
              form.setFields([
                {
                  name: 'value',
                  errors: ['Такого ключа немає в реєстрі налаштувань — оновіть сторінку'],
                },
              ]);
              return;
            }
            if (applyServerErrors(form, error)) return;

            reportFailure(error);
          },
        },
      );
    });
  };

  return (
    <FormModal
      open={setting !== null}
      title={`Налаштування: ${field.label}`}
      isSaving={update.isPending}
      onSubmit={submit}
      onCancel={onClose}
    >
      {setting ? (
        <Form<SettingFormValues>
          key={setting.key}
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{
            value: toFormValue(setting.key, setting.value),
            description: setting.description,
          }}
        >
          <Typography.Paragraph type="secondary" className="numeric">
            {setting.key}
          </Typography.Paragraph>

          <Form.Item
            name="value"
            label={field.label}
            extra={field.hint}
            rules={[requiredRule(), zodRule(field.schema)]}
          >
            {field.kind === 'json' ? (
              <Input.TextArea rows={8} className="numeric" spellCheck={false} />
            ) : (
              <Input
                autoFocus
                {...(field.maxLength === null ? {} : { maxLength: field.maxLength })}
                {...(field.kind === 'text' ? {} : { className: 'numeric' })}
                style={field.kind === 'text' ? undefined : { textTransform: 'uppercase' }}
              />
            )}
          </Form.Item>

          <Form.Item name="description" label="Опис" rules={[zodRule(descriptionSchema)]}>
            <Input.TextArea rows={2} maxLength={255} showCount />
          </Form.Item>
        </Form>
      ) : null}
    </FormModal>
  );
}
