import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import { AuditService } from './audit.service';
import { auditActionLabel, auditEntityLabel, auditEntityRoute } from './audit.types';

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const emptyPage = { items: [], page: 1, pageSize: 25, total: 0 };

const mockFetch = (response: Response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

const urlOf = (fetchMock: ReturnType<typeof vi.fn>): URL =>
  new URL(String((fetchMock.mock.calls[0] as [string, RequestInit])[0]), 'http://localhost');

describe('AuditService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('asks for 25 rows a page unless told otherwise', async () => {
    const fetchMock = mockFetch(json(200, { data: emptyPage }));

    await AuditService.list();

    const url = urlOf(fetchMock);
    expect(url.pathname).toBe('/api/v1/audit');
    expect(url.searchParams.get('page')).toBe('1');
    expect(url.searchParams.get('pageSize')).toBe('25');
  });

  it('sends only the filters that are set', async () => {
    const fetchMock = mockFetch(json(200, { data: emptyPage }));

    await AuditService.list({
      page: 3,
      pageSize: 50,
      action: 'deal.updated',
      createdFrom: '2026-08-01T00:00:00.000Z',
    });

    const url = urlOf(fetchMock);
    expect(url.searchParams.get('page')).toBe('3');
    expect(url.searchParams.get('pageSize')).toBe('50');
    expect(url.searchParams.get('action')).toBe('deal.updated');
    expect(url.searchParams.get('createdFrom')).toBe('2026-08-01T00:00:00.000Z');
    // An absent filter must not travel as the string "undefined".
    expect(url.searchParams.has('entityType')).toBe(false);
    expect(url.searchParams.has('actorId')).toBe(false);
  });

  it('reads the history of one record from its own path', async () => {
    const fetchMock = mockFetch(json(200, { data: emptyPage }));

    await AuditService.history('deal', '3f1b8e60-1b3a-4c5d-9f8e-2a7b6c5d4e3f');

    expect(urlOf(fetchMock).pathname).toBe(
      '/api/v1/audit/deal/3f1b8e60-1b3a-4c5d-9f8e-2a7b6c5d4e3f',
    );
  });

  it('unwraps a single record', async () => {
    const record = { id: 'a-1', action: 'deal.updated' };
    mockFetch(json(200, { data: record }));

    await expect(AuditService.getById('a-1')).resolves.toMatchObject(record);
  });

  it('surfaces a rejected filter as a validation error, not as data', async () => {
    mockFetch(json(400, { error: { code: 'VALIDATION_ERROR', message: 'Invalid request' } }));

    const error = await AuditService.list({ actorId: 'not-a-uuid' }).catch(
      (cause: unknown) => cause,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isValidation).toBe(true);
  });
});

describe('audit dictionaries', () => {
  it('names an action by its verb and leaves an unknown one as it came', () => {
    expect(auditActionLabel('deal.stage_transitioned')).toBe('Зміна стадії');
    expect(auditActionLabel('order.created')).toBe('Створено');
    expect(auditActionLabel('session.opened')).toBe('session.opened');
  });

  it('links only the entities that have a page of their own', () => {
    expect(auditEntityRoute('contact', 'c-1')).toBe('/contacts/c-1');
    expect(auditEntityRoute('stock', 's-1')).toBeNull();
    expect(auditEntityRoute('contact', null)).toBeNull();
    expect(auditEntityLabel('organization_setting')).toBe('Налаштування');
    expect(auditEntityLabel('unheard_of')).toBe('unheard_of');
  });
});
