import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import {
  IntegrationsService,
  isModuleUnavailable,
  isShipmentMissing,
  toAddress,
  toParcel,
  toQuoteRequest,
  toShipmentInput,
} from './integrations.service';
import { DELIVERY_ERROR, type DeliveryQuote } from './integrations.types';
import { isQuoteExpired, normalizeCountry } from './integrations.validation';

const get = vi.fn();
const post = vi.fn();

// Only the transport is replaced: `ApiError` has to stay the real class, or the
// service and the test would each recognise a different one.
vi.mock('@/shared/api', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    http: {
      get: (...args: unknown[]) => get(...args),
      post: (...args: unknown[]) => post(...args),
    },
  };
});

const ADDRESS = { country: 'ua', city: ' Київ ', postalCode: ' 01001 ', line1: ' Хрещатик, 1 ' };
const PARCEL = { weightGrams: 1000, lengthCm: 20, widthCm: 15, heightCm: 10 };

const quote = (expiresAt: string): DeliveryQuote => ({
  quoteId: 'q-1',
  carrier: 'Carrier',
  service: 'express',
  amount: '120.00',
  currency: 'USD',
  estimatedDays: 3,
  expiresAt,
});

describe('normalizeCountry', () => {
  it('keeps two letters in upper case, whatever was typed', () => {
    expect(normalizeCountry('ua')).toBe('UA');
    expect(normalizeCountry('u a 1')).toBe('UA');
  });

  it('refuses to grow past the two characters the API accepts', () => {
    expect(normalizeCountry('uarr')).toBe('UA');
  });
});

describe('toAddress and toParcel', () => {
  it('sends the country the way the API stores it', () => {
    expect(toAddress(ADDRESS).country).toBe('UA');
  });

  it('trims what the operator typed around the value', () => {
    expect(toAddress(ADDRESS)).toEqual({
      country: 'UA',
      city: 'Київ',
      postalCode: '01001',
      line1: 'Хрещатик, 1',
    });
  });

  it('keeps the dimensions whole, as the contract demands', () => {
    expect(toParcel({ ...PARCEL, weightGrams: 1000.7 }).weightGrams).toBe(1000);
  });
});

describe('toQuoteRequest', () => {
  it('omits the declared value when nothing was entered', () => {
    const body = toQuoteRequest({
      orderId: ' ord-1 ',
      origin: ADDRESS,
      destination: ADDRESS,
      parcel: PARCEL,
      declaredValue: '  ',
    });

    expect(body.orderId).toBe('ord-1');
    expect(body).not.toHaveProperty('declaredValue');
  });

  it('normalises the amount through Money, so a typed comma still reaches the API', () => {
    const body = toQuoteRequest({
      orderId: 'ord-1',
      origin: ADDRESS,
      destination: ADDRESS,
      parcel: PARCEL,
      declaredValue: '1234,5',
    });

    expect(body.declaredValue).toBe('1234.50');
  });
});

describe('toShipmentInput', () => {
  it('drops an empty note instead of sending a blank string', () => {
    const body = toShipmentInput({
      quoteId: ' q-1 ',
      orderId: 'ord-1',
      destination: ADDRESS,
      parcel: PARCEL,
      reference: '   ',
    });

    expect(body.quoteId).toBe('q-1');
    expect(body).not.toHaveProperty('reference');
  });

  it('keeps a note the operator wrote', () => {
    expect(
      toShipmentInput({
        quoteId: 'q-1',
        orderId: 'ord-1',
        destination: ADDRESS,
        parcel: PARCEL,
        reference: ' накладна 7 ',
      }).reference,
    ).toBe('накладна 7');
  });
});

describe('isQuoteExpired', () => {
  it('accepts a quote whose deadline is still ahead', () => {
    expect(
      isQuoteExpired(quote('2026-01-01T12:00:00.000Z'), Date.parse('2026-01-01T11:00:00.000Z')),
    ).toBe(false);
  });

  it('marks a quote whose deadline has passed', () => {
    expect(
      isQuoteExpired(quote('2026-01-01T12:00:00.000Z'), Date.parse('2026-01-01T13:00:00.000Z')),
    ).toBe(true);
  });

  it('treats an unreadable deadline as no deadline, rather than as expired', () => {
    expect(isQuoteExpired(quote('never'))).toBe(false);
  });
});

describe('isModuleUnavailable', () => {
  it('recognises a route this API build does not serve', () => {
    expect(isModuleUnavailable(new ApiError({ status: 404, code: 'NOT_FOUND', message: '' }))).toBe(
      true,
    );
  });

  it('recognises a build the request never reached', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: '' })),
    ).toBe(true);
  });

  it('does not mistake a missing shipment for a missing section', () => {
    const error = new ApiError({ status: 404, code: DELIVERY_ERROR.rejected, message: '' });

    expect(isModuleUnavailable(error)).toBe(false);
    expect(isShipmentMissing(error)).toBe(true);
  });

  it('leaves a genuine failure to the error handler', () => {
    expect(
      isModuleUnavailable(
        new ApiError({ status: 503, code: DELIVERY_ERROR.unavailable, message: '' }),
      ),
    ).toBe(false);
    expect(isModuleUnavailable(new Error('boom'))).toBe(false);
  });
});

describe('IntegrationsService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads the health of the integration from its own route', async () => {
    await IntegrationsService.health();

    expect(get).toHaveBeenCalledWith('/integrations/health', {});
  });

  it('passes the abort signal through, so a closed page stops polling', async () => {
    const controller = new AbortController();

    await IntegrationsService.health(controller.signal);

    expect(get).toHaveBeenCalledWith('/integrations/health', { signal: controller.signal });
  });

  it('posts a quote request as the contract describes it', async () => {
    const body = toQuoteRequest({
      orderId: 'ord-1',
      origin: ADDRESS,
      destination: ADDRESS,
      parcel: PARCEL,
    });

    await IntegrationsService.createQuote(body);

    expect(post).toHaveBeenCalledWith('/integrations/delivery/quotes', body);
  });

  it('posts a shipment to the collection route', async () => {
    const body = toShipmentInput({
      quoteId: 'q-1',
      orderId: 'ord-1',
      destination: ADDRESS,
      parcel: PARCEL,
    });

    await IntegrationsService.createShipment(body);

    expect(post).toHaveBeenCalledWith('/integrations/delivery/shipments', body);
  });

  it('reads one shipment by the identifier that was searched for', async () => {
    await IntegrationsService.getShipment(' shp-1 ');

    expect(get).toHaveBeenCalledWith('/integrations/delivery/shipments/shp-1', {});
  });
});
