import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListParams } from '@/shared/hooks';
import { DealsService, toDealListQuery } from './deals.service';
import { asTransitionDetails, type DealFilter, type UpdateDealInput } from './deals.types';

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const remove = vi.fn();

vi.mock('@/shared/api', () => ({
  http: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    patch: (...args: unknown[]) => patch(...args),
    delete: (...args: unknown[]) => remove(...args),
  },
}));

const listParams = (overrides: Partial<ListParams<DealFilter>> = {}): ListParams<DealFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<DealFilter>;

describe('toDealListQuery', () => {
  it('leaves out the filters the user has not set', () => {
    expect(toDealListQuery(listParams())).toEqual({ page: 1, pageSize: 20 });
  });

  it('keeps a stage the API knows and drops one it does not', () => {
    expect(toDealListQuery(listParams({ stage: 'PROPOSAL' })).stage).toBe('PROPOSAL');
    expect(toDealListQuery(listParams({ stage: 'ARCHIVED' })).stage).toBeUndefined();
  });

  it('turns the textual percentage bounds into numbers', () => {
    const query = toDealListQuery(listParams({ minProbability: '0', maxProbability: '80' }));

    expect(query).toMatchObject({ minProbability: 0, maxProbability: 80 });
  });

  it('drops a percentage outside 0..100', () => {
    // A hand-edited link must narrow nothing rather than turn the page into a 400.
    const query = toDealListQuery(listParams({ minProbability: '140', maxProbability: 'дуже' }));

    expect(query.minProbability).toBeUndefined();
    expect(query.maxProbability).toBeUndefined();
  });

  it('drops a sort column the API does not accept', () => {
    const query = toDealListQuery(listParams({ sortBy: 'stage', sortOrder: 'asc' }));

    expect(query.sortBy).toBeUndefined();
    expect(query.sortOrder).toBe('asc');
  });

  it('keeps the amount bounds as the strings the API expects', () => {
    expect(toDealListQuery(listParams({ minAmount: '100.50', maxAmount: '900' }))).toMatchObject({
      minAmount: '100.50',
      maxAmount: '900',
    });
  });
});

describe('DealsService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads the list with the query as request parameters', async () => {
    await DealsService.list({ page: 2, pageSize: 50, search: 'ліц' });

    expect(get).toHaveBeenCalledWith('/deals', {
      params: { page: 2, pageSize: 50, search: 'ліц' },
    });
  });

  it('creates a deal at the collection route', async () => {
    const input = { title: 'Пілот', amount: '1200.00' };

    await DealsService.create(input);

    expect(post).toHaveBeenCalledWith('/deals', input);
  });

  it('never sends the stage in a patch', async () => {
    const input = { version: 3, title: 'Пілот', stage: 'WON' } as unknown as UpdateDealInput;

    await DealsService.update('d-1', input);

    expect(patch).toHaveBeenCalledWith('/deals/d-1', { version: 3, title: 'Пілот' });
  });

  it('keeps an explicit null in a patch, so a link and a date can be cleared', async () => {
    await DealsService.update('d-1', { version: 1, contactId: null, expectedCloseDate: null });

    expect(patch).toHaveBeenCalledWith('/deals/d-1', {
      version: 1,
      contactId: null,
      expectedCloseDate: null,
    });
  });

  it('moves the stage through the transitions route, carrying the version', async () => {
    await DealsService.transition('d-1', { version: 4, stage: 'WON', probability: 100 });

    expect(post).toHaveBeenCalledWith('/deals/d-1/transitions', {
      version: 4,
      stage: 'WON',
      probability: 100,
    });
  });

  it('omits the probability when the caller leaves it to the API', async () => {
    await DealsService.transition('d-1', { version: 4, stage: 'QUALIFIED' });

    expect(post).toHaveBeenCalledWith('/deals/d-1/transitions', { version: 4, stage: 'QUALIFIED' });
  });

  it('sends the read version with a delete', async () => {
    await DealsService.remove('d-1', 7);

    expect(remove).toHaveBeenCalledWith('/deals/d-1', { params: { version: 7 } });
  });
});

describe('asTransitionDetails', () => {
  it('reads the stages a refused move was allowed to reach', () => {
    expect(asTransitionDetails({ from: 'WON', to: 'LOST', allowed: [] })).toEqual({
      from: 'WON',
      to: 'LOST',
      allowed: [],
    });
  });

  it('answers null for anything that is not a refused transition', () => {
    // A version conflict shares the 409 but carries no such details.
    expect(asTransitionDetails(null)).toBeNull();
    expect(asTransitionDetails({ from: 'WON' })).toBeNull();
  });
});
