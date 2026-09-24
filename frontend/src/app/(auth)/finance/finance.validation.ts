import { Money } from '@/lib/money';
import { DEFAULT_REPORT_RANGE } from '@/shared/constants';
import type { MoneyWire } from '@/types/domain';
import type { BankTransaction, MatchCandidate } from './finance.types';

const DAY_MS = 86_400_000;

/** Widest window the summary scans in one request; anything larger answers 400. */
export const MAX_SUMMARY_DAYS = 366;
/**
 * Window applied when the query string names none. A fixed month rather than a
 * stretch measured backwards from the clock; see `shared/constants/reporting`.
 *
 * The summary always opens on this reporting window, independently of the
 * statement list. That makes its request deterministic and lets the card load
 * while the list is still pending.
 */
export const DEFAULT_SUMMARY_RANGE = DEFAULT_REPORT_RANGE;

/** A calendar day as the picker writes it into the query string. */
const CALENDAR_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const isReadableInstant = (value: string): boolean => !Number.isNaN(Date.parse(value));

const readDate = (value: string | undefined): string | undefined =>
  value !== undefined && value !== '' && isReadableInstant(value) ? value : undefined;

export interface CalendarRange {
  readonly from: string;
  readonly to: string;
}

export interface WireRange {
  readonly from: string;
  readonly to: string;
}

export const resolveSummaryRange = (
  from: string | undefined,
  to: string | undefined,
): CalendarRange => ({
  from: readDate(from) ?? DEFAULT_SUMMARY_RANGE.from,
  to: readDate(to) ?? DEFAULT_SUMMARY_RANGE.to,
});

/**
 * A calendar day names a whole day, not its first millisecond. The interval is
 * half-open, so the end is pushed to the following midnight — otherwise picking
 * "today" would ask for a window containing none of today's payments.
 */
export const toWireRange = (range: CalendarRange): WireRange => {
  const start = CALENDAR_PATTERN.test(range.from)
    ? Date.parse(`${range.from}T00:00:00.000Z`)
    : Date.parse(range.from);
  const end = CALENDAR_PATTERN.test(range.to)
    ? Date.parse(`${range.to}T00:00:00.000Z`) + DAY_MS
    : Date.parse(range.to);

  return { from: new Date(start).toISOString(), to: new Date(end).toISOString() };
};

/** Says what is wrong with the chosen window, or nothing when it is usable. */
export const describeRangeIssue = (range: CalendarRange): string | null => {
  const wire = toWireRange(range);
  const from = Date.parse(wire.from);
  const to = Date.parse(wire.to);

  if (Number.isNaN(from) || Number.isNaN(to)) return 'Вкажіть коректні дати періоду';
  if (from >= to) return 'Дата «від» має бути раніша за дату «до»';
  if (to - from > MAX_SUMMARY_DAYS * DAY_MS) {
    return `Період не може перевищувати ${MAX_SUMMARY_DAYS} днів`;
  }
  return null;
};

/**
 * Narrows an amount typed into the URL down to the wire shape the API accepts.
 *
 * The shared list builder has `text`, `oneOf`, `boolean` and `integer`, and an
 * amount is none of the four: passed through as text, `minAmount=багато`
 * reaches the request and turns the whole page into a 400. Parsing it through
 * `Money` both validates it and normalises `1,5` into `"1.50"`, so a filter
 * typed with a comma narrows the list instead of being silently dropped.
 */
export const readAmountFilter = (value: string | undefined): MoneyWire | undefined => {
  if (value === undefined || value === '') return undefined;
  try {
    return Money.fromInput(value).toWire();
  } catch {
    return undefined;
  }
};

/**
 * Why one order is standing in front of the operator as a candidate.
 *
 * `kind` distinguishes a reason the rule acted on from a fact the operator has
 * to weigh, because the two must not look alike: `evidence` is what made this
 * an answer, `caution` is what should slow the click down.
 */
export interface MatchGround {
  readonly key: string;
  readonly kind: 'evidence' | 'caution' | 'neutral';
  readonly text: string;
}

/** Case- and space-insensitive, the way the rule reads a payment reference. */
const flatten = (value: string): string => value.toLowerCase().replace(/\s+/g, '');

const daysBetween = (later: string, earlier: string): number | null => {
  const end = Date.parse(later);
  const start = Date.parse(earlier);
  if (Number.isNaN(end) || Number.isNaN(start)) return null;
  return Math.round((end - start) / DAY_MS);
};

/**
 * Turns one transaction-and-candidate pair into the sentences the choice is
 * made on.
 *
 * This deliberately re-derives nothing the rule owns. The tolerance, the
 * ninety-day window and the list of order statuses are constants of the
 * server's module — the contract says so in as many words, and a second copy
 * here would be a second place to change them from, silently disagreeing with
 * the first. So the amounts are reported as a difference rather than judged as
 * "within tolerance", and the dates as a distance rather than as "inside the
 * window". The verdict stays the server's; the evidence is what the operator
 * could not otherwise see.
 */
export const describeMatch = (
  transaction: BankTransaction,
  candidate: MatchCandidate,
): readonly MatchGround[] => {
  const grounds: MatchGround[] = [];

  const reference = flatten(transaction.reference);
  const number = flatten(candidate.orderNumber);
  if (number !== '' && reference.includes(number)) {
    grounds.push({
      key: 'reference',
      kind: 'evidence',
      text: `У призначенні платежу є номер ${candidate.orderNumber}`,
    });
  }

  // The second route into the rule — the payer being named like the customer —
  // is deliberately not reconstructed here. The build sends the candidate's
  // contact as an identifier and no name, and a hint invented from a name this
  // page happens to have cached would be evidence about a different comparison
  // than the one the server made.

  if (candidate.currency !== transaction.currency) {
    // Nothing in the rule compares currencies, so a same-number order in
    // another currency can arrive here looking like an ordinary answer.
    grounds.push({
      key: 'currency',
      kind: 'caution',
      text: `Валюта замовлення — ${candidate.currency}, платежу — ${transaction.currency}`,
    });
  } else if (transaction.amount === candidate.total) {
    grounds.push({ key: 'amount', kind: 'evidence', text: 'Сума збігається точно' });
  } else {
    const difference = Money.parseOrZero(transaction.amount, transaction.currency).minus(
      Money.parseOrZero(candidate.total, transaction.currency),
    );
    const sign = difference.isNegative ? 'менша на' : 'більша на';
    const size = Money.parseOrZero(
      difference.isNegative ? difference.toWire().slice(1) : difference.toWire(),
      transaction.currency,
    );
    grounds.push({
      key: 'amount',
      kind: 'caution',
      text: `Сума платежу ${sign} ${size.format()} ${transaction.currency}`,
    });
  }

  const distance =
    candidate.placedAt === '' ? null : daysBetween(transaction.bookedAt, candidate.placedAt);
  if (distance !== null) {
    grounds.push(
      distance < 0
        ? {
            key: 'timing',
            kind: 'caution',
            text: `Платіж на ${Math.abs(distance)} дн. раніший за розміщення замовлення`,
          }
        : {
            key: 'timing',
            kind: 'neutral',
            text:
              distance === 0
                ? 'Платіж того самого дня, що й розміщення замовлення'
                : `Платіж через ${distance} дн. після розміщення замовлення`,
          },
    );
  }

  return grounds;
};
