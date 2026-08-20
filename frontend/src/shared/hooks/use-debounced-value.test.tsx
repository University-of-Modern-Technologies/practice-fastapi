import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useDebouncedValue } from './use-debounced-value';
import { act, fireEvent, renderWithProviders, screen } from '@/test/render';

function SearchProbe({ delayMs }: { readonly delayMs?: number }) {
  const [typed, setTyped] = useState('');
  const settled = useDebouncedValue(typed, delayMs);

  return (
    <div>
      <input aria-label="Пошук" value={typed} onChange={(e) => setTyped(e.target.value)} />
      <p data-testid="settled">{settled}</p>
    </div>
  );
}

const type = (text: string): void => {
  fireEvent.change(screen.getByLabelText('Пошук'), { target: { value: text } });
};

const wait = (ms: number): void => {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
};

const settled = (): string => screen.getByTestId('settled').textContent ?? '';

describe('useDebouncedValue', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('не віддає значення, поки користувач ще друкує', () => {
    renderWithProviders(<SearchProbe />);

    type('Ale');
    wait(299);

    expect(settled()).toBe('');
  });

  it('віддає значення, коли друкування спинилося', () => {
    renderWithProviders(<SearchProbe />);

    type('Alex');
    wait(300);

    expect(settled()).toBe('Alex');
  });

  // Four keystrokes must cost one request, not four: this is the whole point of
  // the hook, and the prefixes would answer after the word if they were sent.
  it('пропускає проміжні префікси й лишає тільки останній рядок', () => {
    renderWithProviders(<SearchProbe />);

    type('A');
    wait(200);
    type('Al');
    wait(200);
    type('Ale');
    wait(200);
    type('Alex');

    expect(settled()).toBe('');

    wait(300);
    expect(settled()).toBe('Alex');
  });

  it('поважає власну затримку виклику', () => {
    renderWithProviders(<SearchProbe delayMs={1000} />);

    type('Alex');
    wait(300);
    expect(settled()).toBe('');

    wait(700);
    expect(settled()).toBe('Alex');
  });

  it('віддає початкове значення одразу, без очікування', () => {
    renderWithProviders(<SearchProbe />);
    expect(settled()).toBe('');
  });

  it('доводить до кінця й очищення поля', () => {
    renderWithProviders(<SearchProbe />);

    type('Alex');
    wait(300);
    type('');
    wait(300);

    expect(settled()).toBe('');
  });
});
