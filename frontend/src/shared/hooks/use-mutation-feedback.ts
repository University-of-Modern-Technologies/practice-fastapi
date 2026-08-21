'use client';

import { App } from 'antd';
import { useCallback } from 'react';
import { ApiError } from '@/shared/api';
import { useReportError } from './use-api-error';

/** Maps an API error code to the sentence that explains it in this context. */
export type DomainMessages = Readonly<Record<string, string>>;

/**
 * The two halves of reporting a write. Success is a short confirmation the user
 * can ignore; failure goes through the same reporter as every other error, so a
 * broken save is never silently swallowed.
 *
 * `reportFailure` keeps a single-argument shape so it can be handed straight to
 * `onError`, which calls its handler with the variables as a second argument.
 * A module that needs its own wording builds a reporter with `reportFailureWith`
 * instead: "Недостатньо залишку на складі" tells the operator what to do, while
 * the generic message for the same status does not.
 */
export const useMutationFeedback = (): {
  reportSuccess: (text: string) => void;
  reportFailure: (error: unknown) => void;
  reportFailureWith: (messages: DomainMessages) => (error: unknown) => void;
} => {
  const { message, notification } = App.useApp();
  const reportError = useReportError();

  const reportSuccess = useCallback(
    (text: string) => {
      void message.success(text);
    },
    [message],
  );

  const reportFailureWith = useCallback(
    (messages: DomainMessages) =>
      (error: unknown): void => {
        const known = error instanceof ApiError ? messages[error.code] : undefined;
        if (!known) {
          reportError(error);
          return;
        }
        notification.error({ message: known, placement: 'bottomRight' });
      },
    [notification, reportError],
  );

  return { reportSuccess, reportFailure: reportError, reportFailureWith };
};
