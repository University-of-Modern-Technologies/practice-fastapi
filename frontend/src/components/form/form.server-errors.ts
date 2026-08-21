import type { FormInstance } from 'antd';
import { ApiError } from '@/shared/api';
import type { ValidationDetails } from '@/types/domain';

/** `"body.firstName: Too short"` → `['firstName', 'Too short']`. */
const splitMessage = (message: string): readonly [string, string] | null => {
  const separator = message.indexOf(':');
  if (separator === -1) return null;

  const path = message.slice(0, separator).trim();
  const text = message.slice(separator + 1).trim();
  if (!path || !text) return null;

  // The validator reports the location as a dotted path rooted at the section.
  const field = path.replace(/^(body|query|params)\./, '');
  return field === path && path.includes('.') ? null : [field, text];
};

/**
 * Puts a rejected value back on the field it came from. The API answers a bad
 * request with a flat list of messages; showing them as one banner leaves the
 * user hunting for which of twelve inputs the server disliked.
 *
 * Returns true when at least one message found a home — the caller then skips
 * the generic notification.
 */
export const applyServerErrors = (form: FormInstance, error: unknown): boolean => {
  if (!(error instanceof ApiError) || !error.isValidation) return false;

  const details = error.details as ValidationDetails | null;
  const body = details?.fieldErrors?.body;
  // The envelope is only a contract, not a guarantee: a proxy or an older build
  // may put something else here, and a crash would replace a bad request with a
  // blank page.
  const messages = Array.isArray(body) ? body : [];
  if (messages.length === 0) return false;

  // Every field the form has mounted, whether or not it currently holds an
  // error — `setFields` on a name that is not among them stores a message no
  // one ever draws.
  const mounted = new Set(form.getFieldsError().map(({ name }) => name.join('.')));

  const entries = messages.map(splitMessage);
  const fields = entries
    .filter((entry): entry is readonly [string, string] => entry !== null)
    .filter(([name]) => mounted.has(name))
    .map(([name, message]) => ({ name, errors: [message] }));

  if (fields.length > 0) form.setFields(fields);

  // A message the form could not show has to reach the user some other way, so
  // the generic notification is claimed only when every one of them landed.
  return fields.length === messages.length;
};
