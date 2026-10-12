import { describe, expect, it } from 'vitest';
import { loginSchema, safeNext } from './login.validation';

const ORIGIN = 'https://crm.example.test';

describe('safeNext', () => {
  it('keeps a path on this site with its query and fragment', () => {
    expect(safeNext('/deals/42?tab=history#notes', ORIGIN)).toBe('/deals/42?tab=history#notes');
  });

  it('falls back to the start page when nothing was asked for', () => {
    expect(safeNext(null, ORIGIN)).toBe('/');
    expect(safeNext('', ORIGIN)).toBe('/');
  });

  // Each of these passes a "starts with one slash" test and still leaves the
  // site, because the URL parser strips tabs and newlines and reads `\` as `/`.
  it.each([
    ['протокол-відносна адреса', '//evil.example/login'],
    ['табуляція між слешами', '/\t/evil.example'],
    ['перенос рядка між слешами', '/\n/evil.example'],
    ['зворотний слеш', '/\\evil.example'],
    ['повна адреса іншого сайту', 'https://evil.example/'],
    ['javascript-адреса', 'javascript:alert(1)'],
  ])('не випускає за межі сайту: %s', (_case, value) => {
    expect(safeNext(value, ORIGIN)).toBe('/');
  });

  it('accepts a full address only when it names this very site', () => {
    expect(safeNext(`${ORIGIN}/orders`, ORIGIN)).toBe('/orders');
  });
});

describe('loginSchema', () => {
  // The API refuses a password outside 8…128 characters with a 400; the form
  // says so under the field instead.
  it('applies the bounds the API declares for a password', () => {
    expect(loginSchema.shape.password.safeParse('short').success).toBe(false);
    expect(loginSchema.shape.password.safeParse('x'.repeat(129)).success).toBe(false);
    expect(loginSchema.shape.password.safeParse('long-enough').success).toBe(true);
  });
});
