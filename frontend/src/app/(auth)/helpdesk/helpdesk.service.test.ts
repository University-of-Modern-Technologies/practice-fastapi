import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type { ListParams } from '@/shared/hooks';
import { HelpdeskService, isModuleUnavailable, toTicketListQuery } from './helpdesk.service';
import type { TicketFilter } from './helpdesk.types';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const TICKET_ID = '11111111-1111-1111-1111-111111111111';

const ticket = {
  id: TICKET_ID,
  number: 'TKT-00000042',
  subject: 'Не приходить рахунок',
  body: 'Клієнт не отримав рахунок за серпень.',
  channel: 'EMAIL',
  status: 'OPEN',
  priority: 'HIGH',
  contactId: null,
  assigneeId: null,
  ownerId: '00000000-0000-0000-0000-000000000001',
  openedAt: '2026-08-12T15:23:45.123Z',
  resolvedAt: null,
  version: 3,
  createdAt: '2026-08-12T15:23:45.123Z',
  updatedAt: '2026-08-13T09:00:00.000Z',
};

const stubFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const requestOf = (fetchMock: ReturnType<typeof stubFetch>, call = 0) => {
  const [url, init] = fetchMock.mock.calls[call] as [string, RequestInit];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : (JSON.parse(String(init.body)) as unknown),
  };
};

const params = (overrides: Partial<ListParams<TicketFilter>> = {}): ListParams<TicketFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<TicketFilter>;

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('toTicketListQuery', () => {
  it('переносить у запит лише ті фільтри, які справді стоять', () => {
    const query = toTicketListQuery(
      params({ search: 'рахунок', status: 'OPEN', priority: 'HIGH', openedFrom: '2026-08-01' }),
    );

    expect(query).toEqual({
      page: 1,
      pageSize: 20,
      search: 'рахунок',
      status: 'OPEN',
      priority: 'HIGH',
      openedFrom: '2026-08-01',
    });
  });

  // A hand-edited link is the one place a value the API never agreed to can
  // reach the request; dropping it here keeps the page off a 400.
  it('відкидає стан, канал і пріоритет, яких немає в переліку', () => {
    const query = toTicketListQuery(
      params({ status: 'ON_HOLD', channel: 'TELEPATHY', priority: 'BLOCKER' }),
    );

    expect(query).not.toHaveProperty('status');
    expect(query).not.toHaveProperty('channel');
    expect(query).not.toHaveProperty('priority');
  });

  it('відкидає колонку сортування, за якою API не впорядковує', () => {
    expect(toTicketListQuery(params({ sortBy: 'subject', sortOrder: 'asc' }))).not.toHaveProperty(
      'sortBy',
    );
    expect(toTicketListQuery(params({ sortBy: 'openedAt', sortOrder: 'asc' }))).toMatchObject({
      sortBy: 'openedAt',
      sortOrder: 'asc',
    });
  });
});

describe('HelpdeskService', () => {
  it('читає сторінку з пагінацією, сортуванням і фільтрами, які отримав', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { items: [ticket], page: 2, pageSize: 50, total: 137 } }),
    );

    const page = await HelpdeskService.list({
      page: 2,
      pageSize: 50,
      search: 'рахунок',
      status: 'OPEN',
      ownerId: 'u-1',
      sortBy: 'openedAt',
      sortOrder: 'desc',
    });

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('GET');
    expect(url).toContain('/helpdesk/tickets?');
    expect(url).toContain('page=2');
    expect(url).toContain('pageSize=50');
    expect(url).toContain('status=OPEN');
    expect(url).toContain('ownerId=u-1');
    expect(url).toContain('sortBy=openedAt');
    expect(page.total).toBe(137);
    expect(page.items).toHaveLength(1);
  });

  it('читає одне звернення за ідентифікатором', async () => {
    const fetchMock = stubFetch(json(200, { data: ticket }));

    await expect(HelpdeskService.getById(TICKET_ID)).resolves.toEqual(ticket);
    expect(requestOf(fetchMock).url).toContain(`/helpdesk/tickets/${TICKET_ID}`);
  });

  it('створює звернення без номера і без стану — їх видає сервер', async () => {
    const fetchMock = stubFetch(json(201, { data: ticket }));

    await HelpdeskService.create({
      subject: 'Не приходить рахунок',
      body: 'Клієнт не отримав рахунок за серпень.',
      channel: 'EMAIL',
      priority: 'HIGH',
    });

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/helpdesk\/tickets$/);
    expect(Object.keys(body as object)).not.toContain('number');
    expect(Object.keys(body as object)).not.toContain('status');
  });

  // The status machine is the only way the state moves: a PATCH carrying it
  // would go round both the transition table and `resolvedAt`.
  it('не пропускає стан у PATCH, навіть якщо його підсунули в обʼєкт', async () => {
    const fetchMock = stubFetch(json(200, { data: ticket }));

    await HelpdeskService.update(TICKET_ID, {
      version: 3,
      subject: 'Інша тема',
      status: 'CLOSED',
    } as never);

    const { method, body } = requestOf(fetchMock);
    expect(method).toBe('PATCH');
    expect(body).toEqual({ version: 3, subject: 'Інша тема' });
  });

  it('лишає null у PATCH як «відвʼязати», а відсутність — як «не чіпати»', async () => {
    const fetchMock = stubFetch(json(200, { data: ticket }));

    await HelpdeskService.update(TICKET_ID, { version: 3, contactId: null });

    expect(requestOf(fetchMock).body).toEqual({ version: 3, contactId: null });
  });

  it('надсилає перехід окремою дією і з версією, яку прочитала картка', async () => {
    const fetchMock = stubFetch(json(200, { data: { ...ticket, status: 'RESOLVED' } }));

    await HelpdeskService.transition(TICKET_ID, {
      version: 3,
      toStatus: 'RESOLVED',
      note: 'Рахунок надіслано повторно',
    });

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/helpdesk\/tickets\/[^/]+\/transitions$/);
    expect(body).toEqual({
      version: 3,
      toStatus: 'RESOLVED',
      note: 'Рахунок надіслано повторно',
    });
  });

  // The note is optional in the contract, so an untouched field has to be
  // absent rather than travel as an empty string.
  it('не надсилає порожнього коментаря разом із переходом', async () => {
    const fetchMock = stubFetch(json(200, { data: ticket }));

    await HelpdeskService.transition(TICKET_ID, { version: 3, toStatus: 'OPEN', note: '' });

    expect(Object.keys(requestOf(fetchMock).body as object)).not.toContain('note');
  });

  it('видаляє з версією в рядку запиту — у DELETE немає тіла', async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(HelpdeskService.remove(TICKET_ID, 3)).resolves.toBeUndefined();

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('DELETE');
    expect(url).toContain('version=3');
    expect(body).toBeUndefined();
  });

  it('віддає відмову переходу як ApiError із власним кодом і статусом 422', async () => {
    stubFetch(
      json(422, {
        error: {
          code: 'TICKET_TRANSITION_NOT_ALLOWED',
          message: 'Transition is not allowed',
          details: { from: 'CLOSED', to: 'OPEN', allowed: [] },
        },
        requestId: 'req-42',
      }),
    );

    const error = (await HelpdeskService.transition(TICKET_ID, {
      version: 3,
      toStatus: 'OPEN',
    }).catch((cause: unknown) => cause)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.code).toBe('TICKET_TRANSITION_NOT_ALLOWED');
    expect(error.requestId).toBe('req-42');
  });
});

describe('isModuleUnavailable', () => {
  it('розпізнає збірку API, яка не подає цього розділу', () => {
    expect(isModuleUnavailable(new ApiError({ status: 404, code: 'NOT_FOUND', message: '' }))).toBe(
      true,
    );
  });

  // Both answer 404. Telling an operator that the helpdesk is absent because
  // one ticket is gone would send them to an administrator for nothing.
  it('не плутає відсутній розділ із відсутнім записом', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 404, code: 'TICKET_NOT_FOUND', message: '' })),
    ).toBe(false);
  });

  it('не оголошує розділ відсутнім, коли просто немає звʼязку', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: '' })),
    ).toBe(false);
  });

  it('не привласнює собі помилку сервера', () => {
    expect(isModuleUnavailable(new ApiError({ status: 500, code: 'INTERNAL', message: '' }))).toBe(
      false,
    );
    expect(isModuleUnavailable(new Error('boom'))).toBe(false);
  });
});
