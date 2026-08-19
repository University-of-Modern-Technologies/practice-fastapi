'use client';

import { App } from 'antd';
import { useCallback } from 'react';
import { ApiError } from '@/shared/api';

const MESSAGES: Record<number, string> = {
  0: 'Немає зв’язку із сервером',
  400: 'Перевірте введені дані',
  403: 'Недостатньо прав для цієї дії',
  404: 'Запис не знайдено',
  // Not every 409 is a lost race: entities without `version` answer 409 for a
  // duplicate or a refused transition, and "reload the page" would misdirect.
  409: 'Дію відхилено через поточний стан даних',
  422: 'Перевірте введені дані',
  500: 'Помилка на сервері',
};

export const describeApiError = (error: unknown): string => {
  if (!(error instanceof ApiError)) return 'Сталася непередбачена помилка';
  return MESSAGES[error.status] ?? error.message;
};

/**
 * Reports a failure to the user. Errors surface here rather than in the console,
 * so a broken call is visible instead of silently swallowed.
 */
export const useReportError = (): ((error: unknown) => void) => {
  const { notification } = App.useApp();

  return useCallback(
    (error: unknown) => {
      const requestId = error instanceof ApiError ? error.requestId : null;
      notification.error({
        message: describeApiError(error),
        // The request id ties the message the user sees to a line in the logs.
        ...(requestId ? { description: `ID запиту: ${requestId}` } : {}),
        placement: 'bottomRight',
      });
    },
    [notification],
  );
};
