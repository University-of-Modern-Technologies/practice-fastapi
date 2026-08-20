import { ApiError, http } from '@/shared/api';
import { Money } from '@/lib/money';
import {
  DELIVERY_ERROR,
  type CreateShipmentInput,
  type DeliveryAddress,
  type DeliveryHealth,
  type DeliveryParcel,
  type DeliveryQuote,
  type QuoteRequestInput,
  type Shipment,
} from './integrations.types';
import type {
  AddressFormValues,
  ParcelFormValues,
  QuoteFormValues,
  ShipmentFormValues,
} from './integrations.validation';

const ROUTES = {
  health: '/integrations/health',
  quotes: '/integrations/delivery/quotes',
  shipments: '/integrations/delivery/shipments',
  shipmentById: (id: string): string => `/integrations/delivery/shipments/${id}`,
} as const;

/** The API stores the code upper-cased; sending it that way keeps the two equal. */
export const toAddress = (values: AddressFormValues): DeliveryAddress => ({
  country: values.country.trim().toUpperCase(),
  city: values.city.trim(),
  postalCode: values.postalCode.trim(),
  line1: values.line1.trim(),
});

export const toParcel = (values: ParcelFormValues): DeliveryParcel => ({
  weightGrams: Math.trunc(values.weightGrams),
  lengthCm: Math.trunc(values.lengthCm),
  widthCm: Math.trunc(values.widthCm),
  heightCm: Math.trunc(values.heightCm),
});

/**
 * The declared value is money, so it travels through `Money` rather than
 * through the raw text: a comma typed on a Ukrainian keyboard becomes the dot
 * the API expects, and the scale is the one the server keeps.
 */
export const toQuoteRequest = (values: QuoteFormValues): QuoteRequestInput => {
  const declaredValue = (values.declaredValue ?? '').trim();

  return {
    orderId: values.orderId.trim(),
    origin: toAddress(values.origin),
    destination: toAddress(values.destination),
    parcel: toParcel(values.parcel),
    ...(declaredValue === '' ? {} : { declaredValue: Money.fromInput(declaredValue).toWire() }),
  };
};

export const toShipmentInput = (values: ShipmentFormValues): CreateShipmentInput => {
  const reference = (values.reference ?? '').trim();

  return {
    quoteId: values.quoteId.trim(),
    orderId: values.orderId.trim(),
    destination: toAddress(values.destination),
    parcel: toParcel(values.parcel),
    ...(reference === '' ? {} : { reference }),
  };
};

/**
 * The integration is not part of every API build the client may be pointed at.
 * A route that is absent answers 404, and a build that does not serve it at all
 * fails at the transport — both mean "this section is not here", which is a
 * different thing from "the delivery service is down".
 *
 * The one 404 that is *not* a missing section is the upstream's own "no such
 * shipment": it carries the integration's error code, so the lookup can tell
 * an empty result from an absent module.
 */
export const isModuleUnavailable = (error: unknown): boolean => {
  if (!(error instanceof ApiError)) return false;
  if (error.code === 'NETWORK_ERROR') return true;
  return error.status === 404 && error.code !== DELIVERY_ERROR.rejected;
};

/** «Such a shipment does not exist» — an answer to the search, not a failure. */
export const isShipmentMissing = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404 && error.code === DELIVERY_ERROR.rejected;

export const IntegrationsService = {
  health: (signal?: AbortSignal): Promise<DeliveryHealth> =>
    http.get<DeliveryHealth>(ROUTES.health, { ...(signal ? { signal } : {}) }),

  createQuote: (input: QuoteRequestInput): Promise<DeliveryQuote> =>
    http.post<DeliveryQuote>(ROUTES.quotes, input),

  createShipment: (input: CreateShipmentInput): Promise<Shipment> =>
    http.post<Shipment>(ROUTES.shipments, input),

  getShipment: (id: string, signal?: AbortSignal): Promise<Shipment> =>
    http.get<Shipment>(ROUTES.shipmentById(id.trim()), { ...(signal ? { signal } : {}) }),
};
