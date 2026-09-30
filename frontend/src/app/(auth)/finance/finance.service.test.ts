import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type { ListParams } from '@/shared/hooks';
import {
  FinanceService,
  isModuleUnavailable,
  isProviderUnavailable,
  isVersionConflict,
  toTransactionListQuery,
} from './finance.service';
import { readCandidates, type TransactionFilter } from './finance.types';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const TRANSACTION_ID = '33333333-3333-3333-3333-333333333333';

const transaction = {
  id: TRANSACTION_ID,
  statementId: '44444444-4444-4444-4444-444444444444',
  externalId: 'stub-txn-0007',
  bookedAt: '2026-01-17T10:00:00.000Z',
  amount: '1250.00',
  currency: 'USD',
  direction: 'CREDIT',
  counterpartyName: 'Acme LLC',
  counterpartyAccount: null,
  reference: 'Payment for services',
  matchStatus: 'SUGGESTED',
  matchedOrderId: null,
  matchedAt: null,
  matchedById: null,
  version: 2,
  createdAt: '2026-01-17T10:05:00.000Z',
  updatedAt: '2026-01-17T10:05:00.000Z',
};

const stubFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const requestOf = (fetchMock: ReturnType<typeof stubFetch>, index = 0) => {
  const [url, init] = fetchMock.mock.calls[index] as [string, RequestInit];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : (JSON.parse(String(init.body)) as unknown),
  };
};

const params = (
  overrides: Partial<ListParams<TransactionFilter>> = {},
): ListParams<TransactionFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<TransactionFilter>;

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('toTransactionListQuery', () => {
  it('переносить у запит лише ті фільтри, які справді стоять', () => {
    const query = toTransactionListQuery(
      params({ matchStatus: 'UNMATCHED', direction: 'CREDIT', bookedFrom: '2026-01-01' }),
    );

    expect(query).toEqual({
      page: 1,
      pageSize: 20,
      matchStatus: 'UNMATCHED',
      direction: 'CREDIT',
      bookedFrom: '2026-01-01',
    });
  });

  it('відкидає стан зведення й напрямок, яких немає в переліку', () => {
    const query = toTransactionListQuery(params({ matchStatus: 'ALMOST', direction: 'SIDEWAYS' }));

    expect(query).not.toHaveProperty('matchStatus');
    expect(query).not.toHaveProperty('direction');
  });

  // Money is neither an integer nor free text, and the shared builder has no
  // step for it. Left as text, `minAmount=багато` reaches the API as a 400.
  it('пропускає суму лише в тому вигляді, у якому гроші їдуть дротом', () => {
    expect(toTransactionListQuery(params({ minAmount: '1000' }))).toMatchObject({
      minAmount: '1000.00',
    });
    expect(toTransactionListQuery(params({ maxAmount: '1,5' }))).toMatchObject({
      maxAmount: '1.50',
    });
    expect(toTransactionListQuery(params({ minAmount: 'багато' }))).not.toHaveProperty('minAmount');
  });

  it('відкидає колонку сортування, за якою API не впорядковує', () => {
    expect(
      toTransactionListQuery(params({ sortBy: 'counterpartyName', sortOrder: 'asc' })),
    ).not.toHaveProperty('sortBy');
    expect(toTransactionListQuery(params({ sortBy: 'amount', sortOrder: 'asc' }))).toMatchObject({
      sortBy: 'amount',
      sortOrder: 'asc',
    });
  });
});

describe('FinanceService', () => {
  it('читає сторінку платежів із фільтрами, які отримав', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { items: [transaction], page: 1, pageSize: 20, total: 12 } }),
    );

    const page = await FinanceService.transactions({
      page: 1,
      pageSize: 20,
      matchStatus: 'SUGGESTED',
      minAmount: '100.00',
      sortBy: 'bookedAt',
      sortOrder: 'desc',
    });

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('GET');
    expect(url).toContain('/finance/transactions?');
    expect(url).toContain('matchStatus=SUGGESTED');
    expect(url).toContain('minAmount=100.00');
    expect(page.total).toBe(12);
  });

  it('тягне виписку окремою дією і повертає підсумок імпорту', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { statementId: 'stmt-1', imported: 12, skipped: 0 } }),
    );

    await expect(FinanceService.importStatement()).resolves.toEqual({
      statementId: 'stmt-1',
      imported: 12,
      skipped: 0,
    });

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/finance\/statements\/import$/);
  });

  it('надсилає ручне зведення з версією й замовленням, і більше ні з чим', async () => {
    const fetchMock = stubFetch(json(200, { data: { ...transaction, matchStatus: 'MATCHED' } }));

    await FinanceService.match(TRANSACTION_ID, { version: 2, orderId: 'ord-1' });

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/finance\/transactions\/[^/]+\/match$/);
    expect(body).toEqual({ version: 2, orderId: 'ord-1' });
  });

  // The contract says nothing about a version here, but the module is under
  // optimistic concurrency and publishes its own conflict code. An unmatch that
  // ignored the version would be the one write in the section able to undo
  // somebody else's decision without noticing.
  it('знімає зведення з версією в рядку запиту — у DELETE немає тіла', async () => {
    const fetchMock = stubFetch(json(200, { data: { ...transaction, matchStatus: 'UNMATCHED' } }));

    await FinanceService.unmatch(TRANSACTION_ID, 2);

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('DELETE');
    expect(url).toMatch(/\/finance\/transactions\/[^/]+\/match\?/);
    expect(url).toContain('version=2');
    expect(body).toBeUndefined();
  });

  it('читає підсумок за півінтервалом, який йому дали', async () => {
    const fetchMock = stubFetch(
      json(200, {
        data: {
          from: '2026-01-01T00:00:00.000Z',
          to: '2026-02-01T00:00:00.000Z',
          currency: 'USD',
          totals: { credit: '9000.00', debit: '3000.00', net: '6000.00', transactionCount: 12 },
          matchStatuses: [],
        },
      }),
    );

    await FinanceService.summary({
      from: '2026-01-01T00:00:00.000Z',
      to: '2026-02-01T00:00:00.000Z',
    });

    const { url } = requestOf(fetchMock);
    expect(url).toContain('/finance/summary?');
    expect(url).toContain('from=2026-01-01');
  });

  it('віддає недоступний банк як ApiError із власним кодом', async () => {
    stubFetch(
      json(502, {
        error: { code: 'BANK_PROVIDER_UNAVAILABLE', message: 'Bank is unavailable' },
        requestId: 'req-11',
      }),
    );

    const error = (await FinanceService.importStatement().catch(
      (cause: unknown) => cause,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(isProviderUnavailable(error)).toBe(true);
  });
});

describe('isModuleUnavailable', () => {
  it('розпізнає збірку API, яка не подає цього розділу', () => {
    expect(isModuleUnavailable(new ApiError({ status: 404, code: 'NOT_FOUND', message: '' }))).toBe(
      true,
    );
  });

  // Both answer 404. Telling an operator that finance is absent because one
  // payment is gone would send them to an administrator for nothing.
  it('не плутає відсутній розділ із відсутнім платежем або випискою', () => {
    expect(
      isModuleUnavailable(
        new ApiError({ status: 404, code: 'TRANSACTION_NOT_FOUND', message: '' }),
      ),
    ).toBe(false);
    expect(
      isModuleUnavailable(new ApiError({ status: 404, code: 'STATEMENT_NOT_FOUND', message: '' })),
    ).toBe(false);
  });

  it('не оголошує розділ відсутнім, коли просто немає звʼязку', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: '' })),
    ).toBe(false);
  });
});

describe('isVersionConflict', () => {
  // A 409 carries two different answers, and only one of them is fixed by
  // re-reading. Offering a reload for the other sends the operator to do
  // something that cannot help.
  it('відрізняє програну гонку від відмови самої предметної області', () => {
    expect(
      isVersionConflict(
        new ApiError({ status: 409, code: 'TRANSACTION_CONCURRENT_MODIFICATION', message: '' }),
      ),
    ).toBe(true);
    expect(
      isVersionConflict(
        new ApiError({ status: 409, code: 'TRANSACTION_ALREADY_MATCHED', message: '' }),
      ),
    ).toBe(false);
  });
});

describe('readCandidates', () => {
  // Neither the field carrying the list nor the shape of its elements is
  // written down in the contract, so the card has to survive any of them.
  it('віддає порожній перелік, коли кандидатів у відповіді немає', () => {
    expect(readCandidates(transaction)).toEqual([]);
    expect(readCandidates({ candidates: null })).toEqual([]);
    expect(readCandidates(undefined)).toEqual([]);
  });

  // A candidate without an amount is a button that authorises money nobody can
  // see. It is dropped rather than drawn half-filled.
  it('відкидає кандидата без суми, але лишає тих, у кого вона є', () => {
    const candidates = readCandidates({
      candidates: [
        { orderId: 'ord-1', orderNumber: 'SO-1001', total: '1250.00', currency: 'USD' },
        { orderId: 'ord-2', orderNumber: 'SO-1002' },
        { orderNumber: 'SO-1003', total: '1250.00' },
      ],
    });

    expect(candidates).toHaveLength(1);
    expect(candidates[0]?.orderNumber).toBe('SO-1001');
  });
});
