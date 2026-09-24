'use client';

import { Col, Form, Input, Row, Select, type FormInstance } from 'antd';
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { ConflictAlert, ReferenceSelect, applyServerErrors, zodRule } from '@/components';
import { ApiError } from '@/shared/api';
import {
  useHasPermission,
  useMutationFeedback,
  useUnsavedChanges,
  useVersionConflict,
} from '@/shared/hooks';
import { useResolvedUser, useUserOptions, userLabel } from '../../users/users.queries';
import { useUpdateCall } from '../calls.queries';
import type { Call, UpdateCallInput } from '../calls.types';
import { CALL_NOTES_MAX, callNotesSchema, type CallFormValues } from '../calls.validation';

interface UseCallFormOptions {
  readonly call: Call;
  readonly onSaved: (call: Call) => void;
  /** Re-reads the record after a lost race, so the next save carries the current version. */
  readonly onReload?: (() => unknown) | undefined;
  readonly isReloading?: boolean | undefined;
}

interface UseCallFormResult {
  readonly formProps: {
    readonly form: FormInstance<CallFormValues>;
    readonly initialValues: Partial<CallFormValues>;
    readonly layout: 'vertical';
    readonly requiredMark: boolean;
    readonly onValuesChange: () => void;
    readonly onFinish: () => void;
  };
  readonly fields: ReactNode;
  readonly conflictAlert: ReactNode;
  readonly submit: () => void;
  readonly isSaving: boolean;
  /** Routes a failed write to the field it belongs to; also used by the delete action. */
  readonly handleError: (error: unknown) => void;
}

/**
 * The edit form of a call — and it has only one route, because a call is never
 * typed in by hand. What happened on the line is the provider's record; what
 * the form owns is what the company decided about it afterwards: who is
 * responsible, and what is worth remembering.
 *
 * The contact and the deal are absent from it on purpose. Attaching a call is
 * its own audited action, and a field for it here would offer two ways to do
 * one thing, only one of which the journal records as a linking.
 */
export const useCallForm = ({
  call,
  onSaved,
  onReload,
  isReloading = false,
}: UseCallFormOptions): UseCallFormResult => {
  const [form] = Form.useForm<CallFormValues>();
  const [isDirty, setIsDirty] = useState(false);
  const { reportSuccess, reportFailure } = useMutationFeedback();
  const { hasConflict, handleError: handleConflict, clearConflict } = useVersionConflict();

  const update = useUpdateCall(call.id);

  // Reading accounts is its own permission: without it the picker is not
  // mounted, so the form never fires a request it may not make.
  const canReadUsers = useHasPermission('users', 'read');

  useUnsavedChanges(isDirty);

  const initialValues = useMemo<Partial<CallFormValues>>(
    () => ({
      ...(call.notes === null ? {} : { notes: call.notes }),
      ...(call.ownerId === null ? {} : { ownerId: call.ownerId }),
    }),
    [call],
  );

  const handleError = useCallback(
    (error: unknown) => {
      if (handleConflict(error)) return;

      // Handing a record to somebody else is refused with 403 rather than with
      // a code of its own, so the status is what identifies it here.
      if (
        error instanceof ApiError &&
        error.isForbidden &&
        form.getFieldValue('ownerId') !== call.ownerId
      ) {
        form.setFields([
          { name: 'ownerId', errors: ['Немає прав призначити дзвінок іншому власнику'] },
        ]);
        return;
      }

      if (applyServerErrors(form, error)) return;
      reportFailure(error);
    },
    [call.ownerId, form, handleConflict, reportFailure],
  );

  const submit = useCallback(() => {
    void form
      .validateFields()
      .then((values) => {
        const notes = values.notes?.trim();

        const input: UpdateCallInput = {
          // The version read with the record; a stale one answers 409.
          version: call.version,
          // An emptied field is "there is nothing to say", which is `null` —
          // an empty string would store a note that consists of nothing.
          notes: notes ? notes : null,
          // A call may legitimately end up owned by nobody: that is the state
          // it arrives in, and clearing the picker returns it there.
          ownerId: values.ownerId ?? null,
        };

        update.mutate(input, {
          onSuccess: (saved) => {
            setIsDirty(false);
            clearConflict();
            reportSuccess('Дзвінок збережено');
            onSaved(saved);
          },
          onError: handleError,
        });
      })
      // A form that failed its own rules has already marked the offending
      // fields; there is nothing further to report.
      .catch(() => undefined);
  }, [call.version, clearConflict, form, handleError, onSaved, reportSuccess, update]);

  const reload = useCallback(() => {
    void Promise.resolve(onReload?.()).finally(() => clearConflict());
  }, [clearConflict, onReload]);

  const fields = (
    <Row gutter={16}>
      <Col xs={24} md={8}>
        <Form.Item
          name="ownerId"
          label="Відповідальний"
          extra="Порожнє поле означає, що дзвінок ще ніхто не взяв"
        >
          {canReadUsers ? (
            <ReferenceSelect
              useOptions={useUserOptions}
              useResolved={useResolvedUser}
              getLabel={userLabel}
              placeholder="Нічий"
            />
          ) : (
            <Select disabled placeholder="Нічий" />
          )}
        </Form.Item>
      </Col>

      <Col xs={24} md={16}>
        <Form.Item name="notes" label="Нотатки" rules={[zodRule(callNotesSchema)]}>
          <Input.TextArea
            rows={4}
            maxLength={CALL_NOTES_MAX}
            showCount
            placeholder="Про що говорили, про що домовились"
          />
        </Form.Item>
      </Col>
    </Row>
  );

  return {
    formProps: {
      form,
      initialValues,
      layout: 'vertical',
      requiredMark: false,
      onValuesChange: () => setIsDirty(true),
      onFinish: submit,
    },
    fields,
    conflictAlert: <ConflictAlert open={hasConflict} onReload={reload} isReloading={isReloading} />,
    submit,
    isSaving: update.isPending,
    handleError,
  };
};
