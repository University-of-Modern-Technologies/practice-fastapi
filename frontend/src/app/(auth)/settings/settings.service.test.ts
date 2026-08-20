import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import { SettingsService } from './settings.service';
import type { Setting } from './settings.types';
import { toDisplayValue, toFormValue, toWireValue } from './settings.validation';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const setting: Setting = {
  key: 'organization.defaultCurrency',
  value: 'EUR',
  description: 'Currency applied to new orders and deals.',
  updatedById: 'u-1',
  updatedAt: '2026-08-12T15:23:45.123Z',
  source: 'database',
};

const mockFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const callOf = (fetchMock: ReturnType<typeof vi.fn>): { url: string; init: RequestInit } => {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, init };
};

describe('SettingsService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('reads the whole registry as an array, not as a page', async () => {
    const fetchMock = mockFetch(json(200, { data: [setting] }));

    await expect(SettingsService.list()).resolves.toEqual([setting]);
    expect(callOf(fetchMock).url).toBe('/api/v1/settings');
  });

  it('escapes the key in the path so a dotted key stays one segment', async () => {
    const fetchMock = mockFetch(json(200, { data: setting }));

    await SettingsService.getByKey('organization.defaultCurrency');

    const { url, init } = callOf(fetchMock);
    expect(url).toBe('/api/v1/settings/organization.defaultCurrency');
    expect(init.method).toBe('GET');
  });

  it('writes a value with PUT and carries the description when given', async () => {
    const fetchMock = mockFetch(json(200, { data: setting }));

    await SettingsService.update('orders.numberPrefix', { value: 'INV', description: 'Prefix' });

    const { url, init } = callOf(fetchMock);
    expect(url).toBe('/api/v1/settings/orders.numberPrefix');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(String(init.body))).toEqual({ value: 'INV', description: 'Prefix' });
  });

  it('resets a key with DELETE and resolves on an empty 204', async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }));

    await expect(SettingsService.reset('warehouse.defaultCode')).resolves.toBeUndefined();
    expect(callOf(fetchMock).init.method).toBe('DELETE');
  });

  it('surfaces an unknown key as a 400 with its own code', async () => {
    mockFetch(
      json(400, { error: { code: 'UNKNOWN_SETTING_KEY', message: 'Unknown setting key: nope' } }),
    );

    const error = await SettingsService.getByKey('nope').catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: 'UNKNOWN_SETTING_KEY' });
  });
});

describe('setting value conversion', () => {
  it('upper-cases a code before it is sent, matching what the API stores', () => {
    expect(toWireValue('organization.defaultCurrency', ' eur ')).toBe('EUR');
    expect(toWireValue('orders.numberPrefix', 'inv-a')).toBe('INV-A');
  });

  it('leaves free text as typed apart from trimming', () => {
    expect(toWireValue('organization.name', '  Acme  ')).toBe('Acme');
  });

  it('parses an unknown key as JSON so a structured value survives the trip', () => {
    expect(toWireValue('some.future.key', '{"a":1}')).toEqual({ a: 1 });
    expect(toFormValue('some.future.key', { a: 1 })).toBe('{\n  "a": 1\n}');
  });

  it('shows an absent value as a dash rather than as "null"', () => {
    expect(toDisplayValue(null)).toBe('—');
    expect(toDisplayValue('USD')).toBe('USD');
  });
});
