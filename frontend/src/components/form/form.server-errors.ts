import type { FormInstance } from 'antd';
import { ApiError } from '@/shared/api';
import type { ValidationDetails } from '@/types/domain';

/** A field path as a validator writes it: `email`, `items.0.quantity`. No spaces. */
const PATH_PATTERN = /^[A-Za-z_$][\w$]*(?:\.[\w$]+)*$/;

/** A path rooted at the request part rather than inside it. */
const LOCATION_PREFIX = /^(?:body|query|params)\./;

type FieldPath = readonly (string | number)[];

/**
 * `"email: value is not a valid email address"` → `[['email'], '…']`,
 * `"items.0.quantity: …"` → `[['items', 0, 'quantity'], '…']`.
 *
 * Only a prefix that reads as a field path counts. A message without one —
 * `"Too small: expected string to have >=2 characters"` — has a colon too,
 * and splitting it there would invent a field called "Too small".
 */
const splitMessage = (message: string): readonly [FieldPath, string] | null => {
  const separator = message.indexOf(':');
  if (separator === -1) return null;

  const path = message.slice(0, separator).trim();
  const text = message.slice(separator + 1).trim();
  if (!text || !PATH_PATTERN.test(path)) return null;

  const segments = path
    .replace(LOCATION_PREFIX, '')
    .split('.')
    .map((segment) => (/^\d+$/.test(segment) ? Number(segment) : segment));
  return [segments, text];
};

const keyOf = (path: FieldPath): string => path.join('.');

/**
 * Puts a rejected value back on the field it came from. The API answers a bad
 * request with a flat list of messages; showing them as one banner leaves the
 * user hunting for which of twelve inputs the server disliked.
 *
 * The two backends word that list differently (see `ValidationDetails`): one
 * writes the field path in front of each message, the other sends the bare
 * messages. Only the first kind can be placed; the second is left, untouched,
 * to the generic notification.
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
  const mounted = new Set(form.getFieldsError().map(({ name }) => keyOf(name)));

  const entries = messages
    .filter((message): message is string => typeof message === 'string')
    .map(splitMessage);
  const fields = entries
    .filter((entry): entry is readonly [FieldPath, string] => entry !== null)
    .filter(([path]) => mounted.has(keyOf(path)))
    .map(([path, message]) => ({ name: [...path], errors: [message] }));

  if (fields.length > 0) form.setFields(fields);

  // A message the form could not show has to reach the user some other way, so
  // the generic notification is claimed only when every one of them landed.
  return fields.length === messages.length;
};
