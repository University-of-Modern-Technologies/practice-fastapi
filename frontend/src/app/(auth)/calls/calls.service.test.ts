import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type { ListParams } from '@/shared/hooks';
import {
  CallsService,
  isModuleUnavailable,
  isProviderUnavailable,
  isRecordingUnavailable,
  toCallListQuery,
} from './calls.service';
import type { CallFilter } from './calls.types';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const CALL_ID = '22222222-2222-2222-2222-222222222222';

const call = {
  id: CALL_ID,
  externalId: 'pbx-000917',
  direction: 'INBOUND',
  disposition: 'ANSWERED',
  fromNumber: '+380671234567',
  toNumber: '+380442223344',
  startedAt: '2026-08-12T15:23:45.123Z',
  durationSeconds: 155,
  contactId: null,
  dealId: null,
  ownerId: null,
  recordingUrl: null,
  notes: null,
  version: 3,
  createdAt: '2026-08-12T15:24:00.000Z',
  updatedAt: '2026-08-12T15:24:00.000Z',
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

const params = (overrides: Partial<ListParams<CallFilter>> = {}): ListParams<CallFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<CallFilter>;

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('toCallListQuery', () => {
  it('переносить у запит лише ті фільтри, які справді стоять', () => {
    const query = toCallListQuery(
      params({ direction: 'INBOUND', disposition: 'NO_ANSWER', startedFrom: '2026-08-01' }),
    );

    expect(query).toEqual({
      page: 1,
      pageSize: 20,
      direction: 'INBOUND',
      disposition: 'NO_ANSWER',
      startedFrom: '2026-08-01',
    });
  });

  // A hand-edited link is the one place a value the API never agreed to can
  // reach the request; dropping it here keeps the page off a 400.
  it('відкидає напрямок і результат, яких немає в переліку', () => {
    const query = toCallListQuery(params({ direction: 'SIDEWAYS', disposition: 'MAYBE' }));

    expect(query).not.toHaveProperty('direction');
    expect(query).not.toHaveProperty('disposition');
  });

  // The triage queue is "calls nobody has attributed yet", and it is reached by
  // `hasContact=false` — so the false value has to survive as a value.
  it('передає «без контакту» саме як false, а не як відсутній фільтр', () => {
    expect(toCallListQuery(params({ hasContact: 'false' }))).toMatchObject({ hasContact: false });
    expect(toCallListQuery(params({ hasContact: 'true' }))).toMatchObject({ hasContact: true });
    expect(toCallListQuery(params({ hasContact: 'хтозна' }))).not.toHaveProperty('hasContact');
  });

  it('відкидає колонку сортування, за якою API не впорядковує', () => {
    expect(toCallListQuery(params({ sortBy: 'fromNumber', sortOrder: 'asc' }))).not.toHaveProperty(
      'sortBy',
    );
    expect(toCallListQuery(params({ sortBy: 'durationSeconds', sortOrder: 'asc' }))).toMatchObject({
      sortBy: 'durationSeconds',
      sortOrder: 'asc',
    });
  });
});

describe('CallsService', () => {
  it('читає сторінку з пагінацією, сортуванням і фільтрами, які отримав', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { items: [call], page: 2, pageSize: 50, total: 137 } }),
    );

    const page = await CallsService.list({
      page: 2,
      pageSize: 50,
      direction: 'INBOUND',
      hasContact: false,
      sortBy: 'startedAt',
      sortOrder: 'desc',
    });

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('GET');
    expect(url).toContain('/calls?');
    expect(url).toContain('page=2');
    expect(url).toContain('direction=INBOUND');
    expect(url).toContain('hasContact=false');
    expect(url).toContain('sortBy=startedAt');
    expect(page.total).toBe(137);
  });

  it('читає один дзвінок за ідентифікатором', async () => {
    const fetchMock = stubFetch(json(200, { data: call }));

    await expect(CallsService.getById(CALL_ID)).resolves.toEqual(call);
    expect(requestOf(fetchMock).url).toContain(`/calls/${CALL_ID}`);
  });

  it('тягне пачку від провайдера окремою дією і повертає підсумок', async () => {
    const fetchMock = stubFetch(json(200, { data: { fetched: 12, created: 3, skipped: 9 } }));

    await expect(CallsService.sync()).resolves.toEqual({ fetched: 12, created: 3, skipped: 9 });

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/calls\/sync$/);
  });

  // The contract lets a PATCH carry four fields. Anything else — the numbers,
  // the disposition, the provider's own identifier — is the provider's record
  // of what happened, not something the operator revises afterwards.
  it('не пропускає в PATCH полів, яких контракт там не дозволяє', async () => {
    const fetchMock = stubFetch(json(200, { data: call }));

    await CallsService.update(CALL_ID, {
      version: 3,
      notes: 'Передзвонити у вівторок',
      direction: 'OUTBOUND',
      durationSeconds: 999,
      externalId: 'pbx-000918',
    } as never);

    const { method, body } = requestOf(fetchMock);
    expect(method).toBe('PATCH');
    expect(body).toEqual({ version: 3, notes: 'Передзвонити у вівторок' });
  });

  it('лишає null у PATCH як «відвʼязати», а відсутність — як «не чіпати»', async () => {
    const fetchMock = stubFetch(json(200, { data: call }));

    await CallsService.update(CALL_ID, { version: 3, contactId: null, ownerId: null });

    expect(requestOf(fetchMock).body).toEqual({ version: 3, contactId: null, ownerId: null });
  });

  it('надсилає привʼязку окремою дією, з версією і лише з тим, що вибрали', async () => {
    const fetchMock = stubFetch(json(200, { data: { ...call, contactId: 'c-1' } }));

    await CallsService.link(CALL_ID, { version: 3, contactId: 'c-1' });

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/calls\/[^/]+\/link$/);
    expect(body).toEqual({ version: 3, contactId: 'c-1' });
    expect(Object.keys(body as object)).not.toContain('dealId');
  });

  it('просить адресу запису окремим запитом і віддає строк її дії', async () => {
    const fetchMock = stubFetch(
      json(200, {
        data: { url: 'https://recordings.test/pbx-000917.mp3', expiresAt: '2026-08-12T16:00:00Z' },
      }),
    );

    const recording = await CallsService.recording(CALL_ID);

    expect(requestOf(fetchMock).url).toMatch(/\/calls\/[^/]+\/recording$/);
    expect(recording.expiresAt).toBe('2026-08-12T16:00:00Z');
  });

  it('видаляє з версією в рядку запиту — у DELETE немає тіла', async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(CallsService.remove(CALL_ID, 3)).resolves.toBeUndefined();

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('DELETE');
    expect(url).toContain('version=3');
    expect(body).toBeUndefined();
  });

  it('віддає недоступного провайдера як ApiError зі статусом 502 і власним кодом', async () => {
    stubFetch(
      json(502, {
        error: { code: 'CALL_PROVIDER_UNAVAILABLE', message: 'Provider is unavailable' },
        requestId: 'req-7',
      }),
    );

    const error = (await CallsService.sync().catch((cause: unknown) => cause)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(isProviderUnavailable(error)).toBe(true);
  });
});

describe('isModuleUnavailable', () => {
  it('розпізнає збірку API, яка не подає цього розділу', () => {
    expect(isModuleUnavailable(new ApiError({ status: 404, code: 'NOT_FOUND', message: '' }))).toBe(
      true,
    );
  });

  // Both answer 404. Telling an operator that the journal is absent because one
  // call is gone would send them to an administrator for nothing.
  it('не плутає відсутній розділ із відсутнім записом', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 404, code: 'CALL_NOT_FOUND', message: '' })),
    ).toBe(false);
  });

  it('не оголошує розділ відсутнім, коли просто немає звʼязку', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: '' })),
    ).toBe(false);
  });
});

describe('isRecordingUnavailable', () => {
  // Both are 404s on the same path. One says "this call has no recording", the
  // other says "there is no such call" — and they lead the operator elsewhere.
  it('відрізняє відсутній запис від відсутнього дзвінка', () => {
    expect(
      isRecordingUnavailable(
        new ApiError({ status: 404, code: 'CALL_RECORDING_UNAVAILABLE', message: '' }),
      ),
    ).toBe(true);
    expect(
      isRecordingUnavailable(new ApiError({ status: 404, code: 'CALL_NOT_FOUND', message: '' })),
    ).toBe(false);
    expect(isRecordingUnavailable(new Error('boom'))).toBe(false);
  });
});
