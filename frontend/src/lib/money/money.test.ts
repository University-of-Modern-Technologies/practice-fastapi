import { describe, expect, it } from 'vitest';
import { Money, MoneyError } from './money';

describe('Money', () => {
  it('round-trips the wire format without touching the cents', () => {
    for (const value of ['0.00', '0.05', '1234.50', '99999999999.99', '-42.07']) {
      expect(Money.parse(value).toWire()).toBe(value);
    }
  });

  it('pads a single decimal digit to the fixed scale', () => {
    expect(Money.parse('12.5').toWire()).toBe('12.50');
    expect(Money.parse('12').toWire()).toBe('12.00');
  });

  it('rejects anything that is not a monetary amount', () => {
    for (const value of ['', '1.234', 'abc', '1,50', '1.2.3', ' 1.00']) {
      expect(() => Money.parse(value)).toThrow(MoneyError);
    }
  });

  it('adds without the drift a float would introduce', () => {
    // 0.1 + 0.2 !== 0.3 in binary floating point; in minor units it is exact.
    const total = Money.parse('0.10').plus(Money.parse('0.20'));
    expect(total.toWire()).toBe('0.30');
  });

  it('sums a list and multiplies a line', () => {
    const lines = [Money.parse('1200.00'), Money.parse('600.00'), Money.parse('0.05')];
    expect(Money.sum(lines).toWire()).toBe('1800.05');
    expect(Money.parse('1200.00').times(3).toWire()).toBe('3600.00');
  });

  it('refuses to mix currencies instead of producing a plausible wrong total', () => {
    const usd = Money.parse('10.00', 'USD');
    const uah = Money.parse('10.00', 'UAH');
    expect(() => usd.plus(uah)).toThrow(MoneyError);
  });

  it('refuses a fractional quantity', () => {
    expect(() => Money.parse('10.00').times(1.5)).toThrow(MoneyError);
  });

  it('falls back to zero for an absent or broken value', () => {
    expect(Money.parseOrZero(null).toWire()).toBe('0.00');
    expect(Money.parseOrZero(undefined).toWire()).toBe('0.00');
    expect(Money.parseOrZero('not money').toWire()).toBe('0.00');
  });

  it('accepts a comma typed into a form field', () => {
    expect(Money.fromInput('1234,50').toWire()).toBe('1234.50');
    expect(Money.fromInput(99).toWire()).toBe('99.00');
  });

  it('formats with a non-breaking group separator and two decimals', () => {
    // The locale uses a narrow no-break space; comparing digits keeps the test
    // from depending on which space the ICU build emits.
    expect(Money.parse('19466.00').format().replace(/\s/g, ' ')).toBe('19 466,00');
    expect(Money.parse('-42.07').format().replace(/\s/g, ' ')).toBe('-42,07');
  });

  it('reports sign and emptiness', () => {
    expect(Money.zero().isZero).toBe(true);
    expect(Money.parse('-0.01').isNegative).toBe(true);
    expect(Money.parse('0.01').isNegative).toBe(false);
  });
});
