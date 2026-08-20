/**
 * Money on the wire is a fixed-scale decimal string: `"1234.50"`. Turning that
 * into a JavaScript number loses cents the moment amounts are added up, so the
 * value is kept as an integer count of minor units and only ever formatted for
 * display or serialised back to the same string shape.
 */

/** The API stores monetary columns as `Decimal(14, 2)`; the scale never varies. */
const SCALE = 2;
const SCALE_FACTOR = 100n;

const WIRE_PATTERN = /^-?\d+(\.\d{1,2})?$/;

export const DEFAULT_CURRENCY = 'USD';

export class MoneyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MoneyError';
  }
}

/** Splits a validated wire string into whole and fractional minor units. */
const toMinorUnits = (value: string): bigint => {
  const negative = value.startsWith('-');
  const digits = negative ? value.slice(1) : value;
  const [whole = '0', fraction = ''] = digits.split('.');
  const padded = fraction.padEnd(SCALE, '0');
  const minor = BigInt(whole) * SCALE_FACTOR + BigInt(padded);
  return negative ? -minor : minor;
};

export class Money {
  readonly minorUnits: bigint;
  readonly currency: string;

  private constructor(minorUnits: bigint, currency: string) {
    this.minorUnits = minorUnits;
    this.currency = currency;
  }

  /** Builds an amount from the string the API returned. */
  static parse(value: string, currency: string = DEFAULT_CURRENCY): Money {
    if (!WIRE_PATTERN.test(value)) {
      throw new MoneyError(`Not a monetary amount: ${value}`);
    }
    return new Money(toMinorUnits(value), currency);
  }

  /**
   * Same as `parse`, but a malformed or absent value yields zero instead of
   * throwing. Used in table cells, where one bad row must not blank the page.
   */
  static parseOrZero(value: string | null | undefined, currency: string = DEFAULT_CURRENCY): Money {
    if (value === null || value === undefined || !WIRE_PATTERN.test(value)) {
      return Money.zero(currency);
    }
    return new Money(toMinorUnits(value), currency);
  }

  static zero(currency: string = DEFAULT_CURRENCY): Money {
    return new Money(0n, currency);
  }

  /** Builds an amount from a form input, where the user may type a comma. */
  static fromInput(value: string | number, currency: string = DEFAULT_CURRENCY): Money {
    const normalised = String(value).trim().replace(',', '.');
    return Money.parse(normalised, currency);
  }

  static sum(values: readonly Money[]): Money {
    const first = values[0];
    if (first === undefined) return Money.zero();
    return values.slice(1).reduce((total, value) => total.plus(value), first);
  }

  private assertSameCurrency(other: Money): void {
    // Adding dollars to hryvnia is a bug in the caller, not a rounding detail —
    // it has to surface here rather than produce a plausible wrong total.
    if (this.currency !== other.currency) {
      throw new MoneyError(`Currency mismatch: ${this.currency} and ${other.currency}`);
    }
  }

  plus(other: Money): Money {
    this.assertSameCurrency(other);
    return new Money(this.minorUnits + other.minorUnits, this.currency);
  }

  minus(other: Money): Money {
    this.assertSameCurrency(other);
    return new Money(this.minorUnits - other.minorUnits, this.currency);
  }

  /** Multiplies by a whole quantity — line totals are the only use. */
  times(quantity: number): Money {
    if (!Number.isInteger(quantity)) {
      throw new MoneyError(`Quantity must be a whole number: ${quantity}`);
    }
    return new Money(this.minorUnits * BigInt(quantity), this.currency);
  }

  get isZero(): boolean {
    return this.minorUnits === 0n;
  }

  get isNegative(): boolean {
    return this.minorUnits < 0n;
  }

  /** Serialises back to the exact shape the API accepts. */
  toWire(): string {
    const negative = this.minorUnits < 0n;
    const absolute = negative ? -this.minorUnits : this.minorUnits;
    const whole = absolute / SCALE_FACTOR;
    const fraction = (absolute % SCALE_FACTOR).toString().padStart(SCALE, '0');
    return `${negative ? '-' : ''}${whole}.${fraction}`;
  }

  /** A number is safe here: the value has already been rounded to the scale. */
  private toNumber(): number {
    return Number(this.toWire());
  }

  format(options?: { showCurrency?: boolean }): string {
    const formatter = new Intl.NumberFormat('uk-UA', {
      minimumFractionDigits: SCALE,
      maximumFractionDigits: SCALE,
      ...(options?.showCurrency ? { style: 'currency' as const, currency: this.currency } : {}),
    });
    return formatter.format(this.toNumber());
  }

  toString(): string {
    return this.toWire();
  }
}
