import { describe, expect, it } from 'vitest';
import { describeMatch, readAmountFilter } from './finance.validation';
import type { BankTransaction, MatchCandidate } from './finance.types';

const transaction = (overrides: Partial<BankTransaction> = {}): BankTransaction => ({
  id: 'txn-1',
  statementId: 'stmt-1',
  externalId: 'stub-txn-0001',
  bookedAt: '2026-01-05T10:00:00.000Z',
  amount: '1250.00',
  currency: 'USD',
  direction: 'CREDIT',
  counterpartyName: 'Acme LLC',
  counterpartyAccount: null,
  reference: 'Оплата за рахунком SO-1001',
  matchStatus: 'SUGGESTED',
  matchedOrderId: null,
  matchedAt: null,
  matchedById: null,
  version: 1,
  createdAt: '2026-01-05T10:05:00.000Z',
  updatedAt: '2026-01-05T10:05:00.000Z',
  ...overrides,
});

const candidate = (overrides: Partial<MatchCandidate> = {}): MatchCandidate => ({
  orderId: 'ord-1',
  orderNumber: 'SO-1001',
  total: '1250.00',
  currency: 'USD',
  status: 'CONFIRMED',
  contactId: 'contact-1',
  placedAt: '2026-01-01T09:00:00.000Z',
  ...overrides,
});

const texts = (grounds: readonly { readonly text: string }[]): string =>
  grounds.map((ground) => ground.text).join(' | ');

describe('describeMatch — чому цей кандидат тут', () => {
  // The whole point of the SUGGESTED screen. Without the reasons, every row
  // looks equally plausible and the operator picks the first one.
  it('називає номер у призначенні платежу', () => {
    const grounds = describeMatch(transaction(), candidate());

    expect(texts(grounds)).toContain('У призначенні платежу є номер SO-1001');
  });

  // The rule reads the reference ignoring case and spaces, so the explanation
  // has to recognise the same match the rule did.
  it('бачить номер попри регістр і пробіли, як і саме правило', () => {
    const grounds = describeMatch(
      transaction({ reference: 'оплата so - 1 0 0 1 від клієнта' }),
      candidate({ orderNumber: 'SO-1001' }),
    );

    expect(texts(grounds)).toContain('У призначенні платежу є номер SO-1001');
  });

  // The second route into the rule — the payer named like the customer — is
  // not reconstructed here: the build sends the candidate's contact as an
  // identifier and no name, so there is nothing to compare the payer with.
  it('мовчить про платника, бо збіг за іменем перевіряє сервер, а не клієнт', () => {
    const grounds = describeMatch(
      transaction({ reference: 'Оплата за договором' }),
      candidate(),
    );

    expect(texts(grounds)).not.toContain('Платник');
    expect(texts(grounds)).not.toContain('У призначенні платежу');
  });

  it('каже про точний збіг суми словами, а не мовчанням', () => {
    expect(texts(describeMatch(transaction(), candidate()))).toContain('Сума збігається точно');
  });

  // The fixture has a payment a cent short on purpose. The tolerance is the
  // server's constant, so the difference is reported as a fact and never
  // judged as "within tolerance" here.
  it('показує розбіжність суми як величину, а не як вирок', () => {
    const grounds = describeMatch(transaction({ amount: '1249.99' }), candidate());

    expect(texts(grounds)).toContain('менша на');
    expect(texts(grounds)).toContain('0,01');
  });

  it('показує й перевищення суми, і його напрямок', () => {
    expect(texts(describeMatch(transaction({ amount: '1300.00' }), candidate()))).toContain(
      'більша на',
    );
  });

  // Nothing in the rule compares currencies, so a same-number order in another
  // currency can reach this list looking like an ordinary answer.
  it('окремо попереджає про іншу валюту замість того, щоб віднімати різні гроші', () => {
    const grounds = describeMatch(transaction(), candidate({ currency: 'EUR' }));

    expect(texts(grounds)).toContain('Валюта замовлення — EUR');
    expect(texts(grounds)).not.toContain('Сума збігається точно');
  });

  // The twelfth row of the fixture exists so the window is exercised at all.
  // The client reports the distance; the verdict stays the server's.
  it('називає платіж, що стався раніше за замовлення, як відстань у днях', () => {
    const grounds = describeMatch(
      transaction({ bookedAt: '2025-09-03T10:00:00.000Z' }),
      candidate({ placedAt: '2026-01-01T09:00:00.000Z' }),
    );

    expect(texts(grounds)).toContain('раніший за розміщення замовлення');
  });

  it('позначає попередження як попередження, а докази як докази', () => {
    const grounds = describeMatch(transaction({ amount: '1249.99' }), candidate());

    expect(grounds.filter((ground) => ground.kind === 'evidence').length).toBeGreaterThan(0);
    expect(grounds.filter((ground) => ground.kind === 'caution').length).toBeGreaterThan(0);
  });
});

describe('readAmountFilter', () => {
  it('нормалізує введене в той рядок, яким гроші їдуть дротом', () => {
    expect(readAmountFilter('1000')).toBe('1000.00');
    expect(readAmountFilter('1,5')).toBe('1.50');
    expect(readAmountFilter(' 12.34 ')).toBe('12.34');
  });

  it('відкидає те, що сумою не є', () => {
    expect(readAmountFilter('багато')).toBeUndefined();
    expect(readAmountFilter('')).toBeUndefined();
    expect(readAmountFilter(undefined)).toBeUndefined();
  });
});
