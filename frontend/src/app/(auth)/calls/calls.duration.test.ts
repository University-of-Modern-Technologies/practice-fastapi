import { describe, expect, it } from 'vitest';
import { formatDuration, spellDuration } from './_components';

describe('formatDuration', () => {
  it('показує хвилини й секунди у формі, яку зручно порівнювати в колонці', () => {
    expect(formatDuration(155)).toBe('2:35');
    expect(formatDuration(59)).toBe('0:59');
    expect(formatDuration(600)).toBe('10:00');
  });

  it('додає години лише тоді, коли вони є', () => {
    expect(formatDuration(3725)).toBe('1:02:05');
    expect(formatDuration(3599)).toBe('59:59');
  });

  // An unanswered call lasted no time at all, and that is a fact about the
  // call. A duration nobody recorded is a different thing and reads as one.
  it('відрізняє нульову тривалість від відсутньої', () => {
    expect(formatDuration(0)).toBe('0:00');
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(undefined)).toBe('—');
  });

  it('не вигадує тривалості з того, що нею не є', () => {
    expect(formatDuration(-5)).toBe('—');
    expect(formatDuration(Number.NaN)).toBe('—');
  });
});

describe('spellDuration', () => {
  it('промовляє ту саму тривалість словами', () => {
    expect(spellDuration(155)).toBe('2 хв 35 с');
    expect(spellDuration(3725)).toBe('1 год 2 хв 5 с');
    expect(spellDuration(120)).toBe('2 хв');
    expect(spellDuration(0)).toBe('0 с');
  });
});
