import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import { ContactsService } from './contacts.service';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const contact = {
  id: 'c-1',
  ownerId: 'u-1',
  firstName: 'Олена',
  lastName: 'Ковальчук',
  email: 'olena@example.com',
  phone: null,
  company: null,
  notes: null,
  createdAt: '2026-08-12T15:23:45.123Z',
  updatedAt: '2026-08-12T15:23:45.123Z',
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

describe('ContactsService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('asks for a page with the paging, sorting and filters it was given', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { items: [contact], page: 2, pageSize: 50, total: 137 } }),
    );

    const page = await ContactsService.list({
      page: 2,
      pageSize: 50,
      search: 'ковальчук',
      ownerId: 'u-1',
      sortBy: 'lastName',
      sortOrder: 'asc',
    });

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('GET');
    expect(url).toContain('/contacts?');
    expect(url).toContain('page=2');
    expect(url).toContain('pageSize=50');
    expect(url).toContain('ownerId=u-1');
    expect(url).toContain('sortBy=lastName');
    expect(url).toContain('sortOrder=asc');
    expect(page.total).toBe(137);
    expect(page.items).toHaveLength(1);
  });

  it('leaves filters that were not set out of the query string', async () => {
    const fetchMock = stubFetch(
      json(200, { data: { items: [], page: 1, pageSize: 20, total: 0 } }),
    );

    await ContactsService.list({ page: 1, search: '' });

    const { url } = requestOf(fetchMock);
    expect(url).not.toContain('search');
    expect(url).not.toContain('ownerId');
    expect(url).not.toContain('sortBy');
  });

  it('reads one contact by id', async () => {
    const fetchMock = stubFetch(json(200, { data: contact }));

    await expect(ContactsService.getById('c-1')).resolves.toEqual(contact);
    expect(requestOf(fetchMock).url).toContain('/contacts/c-1');
  });

  it('creates a contact with the body it was handed', async () => {
    const fetchMock = stubFetch(json(201, { data: contact }));

    await ContactsService.create({
      firstName: 'Олена',
      lastName: 'Ковальчук',
      email: 'olena@example.com',
    });

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('POST');
    expect(url).toMatch(/\/contacts$/);
    expect(body).toEqual({
      firstName: 'Олена',
      lastName: 'Ковальчук',
      email: 'olena@example.com',
    });
  });

  it('patches only the fields it was given and keeps null as "clear this"', async () => {
    const fetchMock = stubFetch(json(200, { data: { ...contact, company: null } }));

    await ContactsService.update('c-1', { company: null, phone: '+380501234567' });

    const { url, method, body } = requestOf(fetchMock);
    expect(method).toBe('PATCH');
    expect(url).toContain('/contacts/c-1');
    expect(body).toEqual({ company: null, phone: '+380501234567' });
    expect(Object.keys(body as object)).not.toContain('firstName');
  });

  it('deletes without sending a version — a contact has none', async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(ContactsService.remove('c-1')).resolves.toBeUndefined();

    const { url, method } = requestOf(fetchMock);
    expect(method).toBe('DELETE');
    expect(url).toMatch(/\/contacts\/c-1$/);
    expect(url).not.toContain('version');
  });

  it('surfaces the missing-channel refusal as an ApiError with its own code', async () => {
    stubFetch(
      json(400, {
        error: { code: 'CONTACT_CHANNEL_REQUIRED', message: 'Email or phone is required' },
        requestId: 'req-42',
      }),
    );

    const error = (await ContactsService.create({
      firstName: 'Олена',
      lastName: 'Ковальчук',
    }).catch((cause: unknown) => cause)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('CONTACT_CHANNEL_REQUIRED');
    expect(error.status).toBe(400);
    expect(error.requestId).toBe('req-42');
  });
});
