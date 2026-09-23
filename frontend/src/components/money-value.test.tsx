import { describe, expect, it } from 'vitest';
import { MoneyValue } from './money-value';
import { renderWithProviders, screen } from '@/test/render';

/** uk-UA groups with a non-breaking space, which no assertion should depend on. */
const shown = (): string => (screen.getByTestId('amount').textContent ?? '').replace(/ /g, ' ');

const render = (element: React.ReactElement): void => {
  renderWithProviders(<span data-testid="amount">{element}</span>);
};

describe('MoneyValue', () => {
  it('форматує суму з роздільником тисяч і комою', () => {
    render(<MoneyValue value="1234.50" />);
    expect(shown()).toBe('1 234,50');
  });

  it('показує нуль як суму, а не як прочерк', () => {
    render(<MoneyValue value="0.00" />);
    expect(shown()).toBe('0,00');
  });

  // The whole reason money never becomes a float: a sum this size loses its
  // cents on the way through `Number` if the string is parsed rather than
  // counted in minor units.
  it('не втрачає копійки на великій сумі', () => {
    render(<MoneyValue value="99999999999.99" />);
    expect(shown()).toBe('99 999 999 999,99');
  });

  it('показує прочерк, коли суми немає', () => {
    render(<MoneyValue value={null} />);
    expect(shown()).toBe('—');
  });

  it('показує прочерк для невизначеної суми', () => {
    render(<MoneyValue value={undefined} />);
    expect(shown()).toBe('—');
  });

  it('додає позначку валюти на вимогу', () => {
    render(<MoneyValue value="1234.50" currency="EUR" showCurrency />);
    expect(shown()).toContain('EUR');
  });

  it('бере валюту з переданого коду, а не припускає одну на всіх', () => {
    render(<MoneyValue value="1234.50" currency="UAH" showCurrency />);
    expect(shown()).toContain('₴');
  });

  it('за замовчуванням валюту не показує', () => {
    render(<MoneyValue value="1234.50" currency="UAH" />);
    expect(shown()).not.toContain('₴');
  });
});
