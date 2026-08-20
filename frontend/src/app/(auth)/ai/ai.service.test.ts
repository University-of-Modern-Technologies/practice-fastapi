import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import { AiService, isModuleUnavailable, toDealSummaryBody, toInquiryBody } from './ai.service';

const post = vi.fn();

// Only the transport is replaced: `ApiError` has to stay the real class, or the
// service and the test would each recognise a different one.
vi.mock('@/shared/api', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, http: { post: (...args: unknown[]) => post(...args) } };
});

const DEAL_ID = '3f1d2c4e-5b6a-4c8d-9e0f-1a2b3c4d5e6f';

describe('toDealSummaryBody', () => {
  it('sends the required fields as the contract spells them', () => {
    expect(toDealSummaryBody({ id: DEAL_ID, title: ' Постачання ', stage: ' QUALIFIED ' })).toEqual(
      {
        id: DEAL_ID,
        title: 'Постачання',
        stage: 'QUALIFIED',
      },
    );
  });

  it('drops an optional field that is absent instead of sending an empty value', () => {
    const body = toDealSummaryBody({
      id: DEAL_ID,
      title: 'Постачання',
      stage: 'LEAD',
      amount: '',
      notes: '   ',
    });

    expect(body).not.toHaveProperty('amount');
    expect(body).not.toHaveProperty('notes');
  });

  it('keeps a zero probability, which is a value and not an absence', () => {
    expect(
      toDealSummaryBody({ id: DEAL_ID, title: 'X', stage: 'LOST', probability: 0 }),
    ).toMatchObject({ probability: 0 });
  });

  it('normalises the currency the way the API stores it', () => {
    expect(
      toDealSummaryBody({ id: DEAL_ID, title: 'X', stage: 'LEAD', currency: 'usd' }),
    ).toMatchObject({ currency: 'USD' });
  });

  it('forwards nothing beyond the allow-list, whatever the caller put on the object', () => {
    const input = {
      id: DEAL_ID,
      title: 'X',
      stage: 'LEAD',
      // A field the deal entity carries but the contract never accepts.
      ownerId: 'a0000000-0000-0000-0000-000000000000',
      version: 7,
    };

    expect(Object.keys(toDealSummaryBody(input))).toEqual(['id', 'title', 'stage']);
  });
});

describe('toInquiryBody', () => {
  it('sends the trimmed text and nothing else', () => {
    expect(toInquiryBody({ text: '  Не прийшла посилка  ' })).toEqual({
      text: 'Не прийшла посилка',
    });
  });
});

describe('isModuleUnavailable', () => {
  it('recognises a route the API build does not serve', () => {
    expect(isModuleUnavailable(new ApiError({ status: 404, code: 'NOT_FOUND', message: '' }))).toBe(
      true,
    );
  });

  it('recognises a build the request never reached', () => {
    expect(
      isModuleUnavailable(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: '' })),
    ).toBe(true);
  });

  it('leaves a genuine failure to the error handler', () => {
    expect(isModuleUnavailable(new ApiError({ status: 500, code: 'INTERNAL', message: '' }))).toBe(
      false,
    );
    expect(isModuleUnavailable(new ApiError({ status: 403, code: 'FORBIDDEN', message: '' }))).toBe(
      false,
    );
    expect(isModuleUnavailable(new Error('boom'))).toBe(false);
  });
});

describe('AiService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('posts the summary to its own route', async () => {
    await AiService.summariseDeal({ id: DEAL_ID, title: 'Постачання', stage: 'LEAD' });

    expect(post).toHaveBeenCalledWith(
      '/ai/summaries/deal',
      { id: DEAL_ID, title: 'Постачання', stage: 'LEAD' },
      {},
    );
  });

  it('posts the classification to its own route', async () => {
    await AiService.classifyInquiry({ text: 'Рахунок виставлено двічі' });

    expect(post).toHaveBeenCalledWith(
      '/ai/classify/inquiry',
      { text: 'Рахунок виставлено двічі' },
      {},
    );
  });

  it('passes the abort signal through, so a left page stops waiting on the model', async () => {
    const controller = new AbortController();

    await AiService.classifyInquiry({ text: 'Питання' }, controller.signal);

    expect(post).toHaveBeenCalledWith(
      '/ai/classify/inquiry',
      { text: 'Питання' },
      { signal: controller.signal },
    );
  });
});
