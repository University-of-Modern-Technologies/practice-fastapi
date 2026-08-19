import type { CircuitState, ShipmentStatus } from '@/shared/constants';
import type { CurrencyCode, Id, IsoDateTime, MoneyWire } from '@/types/domain';

/**
 * What the operator is allowed to know about the dependency: no base URL, no
 * credentials, no upstream error text — only whether requests are going out.
 */
export interface DeliveryHealth {
  readonly transport: 'stub' | 'http';
  readonly circuitState: CircuitState;
  readonly consecutiveFailures: number;
  readonly lastErrorAt: IsoDateTime | null;
  readonly openedAt: IsoDateTime | null;
}

export interface DeliveryAddress {
  /** ISO 3166-1 alpha-2, upper case. */
  readonly country: string;
  readonly city: string;
  readonly postalCode: string;
  readonly line1: string;
}

export interface DeliveryParcel {
  readonly weightGrams: number;
  readonly lengthCm: number;
  readonly widthCm: number;
  readonly heightCm: number;
}

export interface QuoteRequestInput {
  readonly orderId: string;
  readonly origin: DeliveryAddress;
  readonly destination: DeliveryAddress;
  readonly parcel: DeliveryParcel;
  readonly declaredValue?: MoneyWire;
}

export interface DeliveryQuote {
  readonly quoteId: string;
  readonly carrier: string;
  readonly service: string;
  readonly amount: MoneyWire;
  readonly currency: CurrencyCode;
  readonly estimatedDays: number;
  readonly expiresAt: IsoDateTime;
}

export interface CreateShipmentInput {
  readonly quoteId: string;
  readonly orderId: string;
  readonly destination: DeliveryAddress;
  readonly parcel: DeliveryParcel;
  readonly reference?: string;
}

export interface Shipment {
  readonly shipmentId: Id;
  readonly orderId: string;
  readonly status: ShipmentStatus;
  readonly carrier: string;
  readonly trackingNumber: string | null;
  readonly createdAt: IsoDateTime;
  readonly estimatedDeliveryAt: IsoDateTime | null;
}

/**
 * A quote and the request it answers. The shipment is created against the same
 * destination and parcel the price was calculated for, so keeping them together
 * lets the second form start from facts instead of from retyping.
 */
export interface QuoteResult {
  readonly quote: DeliveryQuote;
  readonly request: QuoteRequestInput;
}

/**
 * The four outcomes the integration reports. They describe the dependency, not
 * the record: none of them means the user typed something wrong.
 */
export const DELIVERY_ERROR = {
  timeout: 'DELIVERY_TIMEOUT',
  unavailable: 'DELIVERY_UNAVAILABLE',
  rejected: 'DELIVERY_REJECTED',
  invalidResponse: 'DELIVERY_INVALID_RESPONSE',
} as const;

/** Wording the operator can act on, instead of a bare status number. */
export const DELIVERY_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  [DELIVERY_ERROR.timeout]: 'Служба доставки не відповіла вчасно — спробуйте ще раз',
  [DELIVERY_ERROR.unavailable]: 'Служба доставки тимчасово недоступна',
  [DELIVERY_ERROR.rejected]: 'Служба доставки відхилила запит — перевірте адресу й габарити',
  [DELIVERY_ERROR.invalidResponse]: 'Служба доставки повернула неочікувану відповідь',
};
