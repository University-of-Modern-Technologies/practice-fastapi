/**
 * The API reports conversion and win rates as a fraction in `[0, 1]`, rounded
 * to four decimals. Every report that shows one has to turn it into a
 * percentage, and three modules doing that arithmetic separately is three
 * chances to display a rate a hundred times off.
 */
export const formatRate = (rate: number | null | undefined, fractionDigits = 1): string => {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—';
  return `${(rate * 100).toFixed(fractionDigits)} %`;
};

/** Whole counts — quantities, row totals — with a group separator. */
export const formatCount = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('uk-UA', { maximumFractionDigits: 0 }).format(value);
};
