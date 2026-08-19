import { Money } from '@/lib/money';
import type { CurrencyCode, MoneyWire } from '@/types/domain';

interface MoneyValueProps {
  readonly value: MoneyWire | null | undefined;
  readonly currency?: CurrencyCode;
  readonly showCurrency?: boolean;
}

/**
 * Renders an amount in the monospaced face with tabular figures, so a column of
 * sums lines up digit under digit and a wrong order of magnitude is visible at
 * a glance rather than only on reading.
 */
export function MoneyValue({ value, currency, showCurrency = false }: MoneyValueProps) {
  if (value === null || value === undefined) return <span className="numeric">—</span>;

  const money = Money.parseOrZero(value, currency);
  return <span className="numeric">{money.format({ showCurrency })}</span>;
}
