import { describe, expect, it } from 'vitest';
import type { ListParams } from '@/shared/hooks';
import { listQuery } from './query-builder';

type TestFilter = 'label' | 'color' | 'level' | 'active';

const SORT_FIELDS = ['name', 'createdAt'] as const;
type SortField = (typeof SORT_FIELDS)[number];
const isSortField = (value: string | undefined): value is SortField =>
  value !== undefined && (SORT_FIELDS as readonly string[]).includes(value);

const params = (overrides: Partial<ListParams<TestFilter>> = {}): ListParams<TestFilter> =>
  ({ page: 1, pageSize: 20, ...overrides }) as ListParams<TestFilter>;

interface TestQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly label?: string;
  readonly color?: string;
  readonly level?: number;
  readonly active?: boolean;
  readonly sortBy?: SortField;
  readonly sortOrder?: 'asc' | 'desc';
}

describe('listQuery', () => {
  it('always carries page and pageSize through', () => {
    expect(listQuery(params()).build<TestQuery>()).toEqual({ page: 1, pageSize: 20 });
  });

  describe('text', () => {
    it('drops an absent or empty value', () => {
      const query = listQuery(params({ label: '' }))
        .text('label')
        .build<TestQuery>();

      expect(query.label).toBeUndefined();
      expect('label' in query).toBe(false);
    });

    it('keeps a non-empty value', () => {
      const query = listQuery(params({ label: 'urgent' }))
        .text('label')
        .build<TestQuery>();

      expect(query.label).toBe('urgent');
    });

    it('truncates to the given length when one is set', () => {
      const query = listQuery(params({ label: 'x'.repeat(10) }))
        .text('label', { maxLength: 4 })
        .build<TestQuery>();

      expect(query.label).toBe('xxxx');
    });
  });

  describe('oneOf', () => {
    it('keeps a value from the allowed set', () => {
      const query = listQuery(params({ color: 'red' }))
        .oneOf('color', ['red', 'blue'])
        .build<TestQuery>();

      expect(query.color).toBe('red');
    });

    it('drops a value outside the allowed set', () => {
      const query = listQuery(params({ color: 'green' }))
        .oneOf('color', ['red', 'blue'])
        .build<TestQuery>();

      expect(query.color).toBeUndefined();
    });
  });

  describe('boolean', () => {
    it('parses the two textual values a checkbox can hold', () => {
      expect(
        listQuery(params({ active: 'true' }))
          .boolean('active')
          .build<TestQuery>().active,
      ).toBe(true);
      expect(
        listQuery(params({ active: 'false' }))
          .boolean('active')
          .build<TestQuery>().active,
      ).toBe(false);
    });

    it('drops anything that is not exactly "true" or "false"', () => {
      const query = listQuery(params({ active: 'yes' }))
        .boolean('active')
        .build<TestQuery>();

      expect(query.active).toBeUndefined();
    });
  });

  describe('integer', () => {
    it('keeps zero — a falsy value that is still a valid bound', () => {
      const query = listQuery(params({ level: '0' }))
        .integer('level', { min: 0, max: 100 })
        .build<TestQuery>();

      expect(query.level).toBe(0);
    });

    it('drops a fraction', () => {
      const query = listQuery(params({ level: '4.5' }))
        .integer('level', { min: 0, max: 100 })
        .build<TestQuery>();

      expect(query.level).toBeUndefined();
    });

    it('drops a value below the minimum', () => {
      const query = listQuery(params({ level: '-1' }))
        .integer('level', { min: 0, max: 100 })
        .build<TestQuery>();

      expect(query.level).toBeUndefined();
    });

    it('drops a value above the maximum', () => {
      const query = listQuery(params({ level: '140' }))
        .integer('level', { min: 0, max: 100 })
        .build<TestQuery>();

      expect(query.level).toBeUndefined();
    });

    it('drops text that does not parse as a number', () => {
      const query = listQuery(params({ level: 'дуже' }))
        .integer('level', { min: 0, max: 100 })
        .build<TestQuery>();

      expect(query.level).toBeUndefined();
    });
  });

  describe('sort', () => {
    it('keeps a sort column the caller recognises', () => {
      const query = listQuery(params({ sortBy: 'name' }))
        .sort(isSortField)
        .build<TestQuery>();

      expect(query.sortBy).toBe('name');
    });

    it('drops a sort column the API does not know', () => {
      const query = listQuery(params({ sortBy: 'unknownColumn' }))
        .sort(isSortField)
        .build<TestQuery>();

      expect(query.sortBy).toBeUndefined();
    });

    it('carries the sort direction through unchanged', () => {
      const query = listQuery(params({ sortBy: 'name', sortOrder: 'desc' }))
        .sort(isSortField)
        .build<TestQuery>();

      expect(query.sortOrder).toBe('desc');
    });
  });
});
