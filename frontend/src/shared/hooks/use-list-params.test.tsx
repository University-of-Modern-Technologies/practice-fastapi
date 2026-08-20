import { describe, expect, it, vi } from 'vitest';
import { useListParams, type ListParamsPatch } from './use-list-params';
import { fireEvent, renderWithProviders, screen } from '@/test/render';

/**
 * The hook keeps the list state in the address bar, so the router is what a
 * test can observe: every assertion here reads the URL the hook asked for.
 */
const nav = vi.hoisted(() => ({ replace: vi.fn(), search: '' }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => '/deals',
  useSearchParams: () => new URLSearchParams(nav.search),
}));

type Filters = 'search' | 'ownerId';

function ListProbe({ patches }: { readonly patches: Record<string, ListParamsPatch<Filters>> }) {
  const { params, setParams, resetParams } = useListParams<Filters>({
    filters: ['search', 'ownerId'],
    defaults: { pageSize: 20, sortBy: 'createdAt', sortOrder: 'desc' },
  });

  return (
    <div>
      <p data-testid="params">{JSON.stringify(params)}</p>
      {Object.entries(patches).map(([label, patch]) => (
        <button key={label} type="button" onClick={() => setParams(patch)}>
          {label}
        </button>
      ))}
      <button type="button" onClick={resetParams}>
        Скинути
      </button>
    </div>
  );
}

const renderList = (
  search: string,
  patches: Record<string, ListParamsPatch<Filters>> = {},
): void => {
  nav.search = search;
  nav.replace.mockClear();
  renderWithProviders(<ListProbe patches={patches} />);
};

const params = (): Record<string, unknown> =>
  JSON.parse(screen.getByTestId('params').textContent ?? '{}') as Record<string, unknown>;

/** The query the hook last asked the router to show. */
const nextQuery = (): URLSearchParams => {
  const url = nav.replace.mock.calls.at(-1)?.[0] as string;
  return new URLSearchParams(url.split('?')[1] ?? '');
};

describe('useListParams', () => {
  it('читає стан списку з посилання, а не починає з нуля', () => {
    renderList('page=3&pageSize=50&sortBy=amount&sortOrder=asc&search=каб');

    expect(params()).toMatchObject({
      page: 3,
      pageSize: 50,
      sortBy: 'amount',
      sortOrder: 'asc',
      search: 'каб',
    });
  });

  it('підставляє значення за замовчуванням, коли посилання порожнє', () => {
    renderList('');

    expect(params()).toMatchObject({
      page: 1,
      pageSize: 20,
      sortBy: 'createdAt',
      sortOrder: 'desc',
    });
  });

  it('ігнорує сміття в номері сторінки замість того, щоб просити нульову', () => {
    renderList('page=0&pageSize=-5');

    expect(params()).toMatchObject({ page: 1, pageSize: 20 });
  });

  it('ігнорує напрям сортування, якого не існує', () => {
    renderList('sortOrder=вниз');

    expect(params().sortOrder).toBe('desc');
  });

  it('не бачить фільтра, якого цей список не знає', () => {
    renderList('stage=WON');

    expect(params()).not.toHaveProperty('stage');
  });

  // Narrowing the list while sitting on page 7 would show an empty table.
  it('скидає сторінку, коли змінився фільтр', () => {
    renderList('page=7&search=каб', { filter: { search: 'кабель' } });

    fireEvent.click(screen.getByRole('button', { name: 'filter' }));

    expect(nextQuery().get('page')).toBeNull();
    expect(nextQuery().get('search')).toBe('кабель');
  });

  it('скидає сторінку, коли змінилося сортування', () => {
    renderList('page=7', { sort: { sortBy: 'amount', sortOrder: 'asc' } });

    fireEvent.click(screen.getByRole('button', { name: 'sort' }));

    expect(nextQuery().get('page')).toBeNull();
    expect(nextQuery().get('sortBy')).toBe('amount');
  });

  it('скидає сторінку, коли змінився розмір сторінки', () => {
    renderList('page=7', { size: { pageSize: 50 } });

    fireEvent.click(screen.getByRole('button', { name: 'size' }));

    expect(nextQuery().get('page')).toBeNull();
    expect(nextQuery().get('pageSize')).toBe('50');
  });

  it('лишає сторінку, коли гортають саме сторінки', () => {
    renderList('search=каб', { paging: { page: 4 } });

    fireEvent.click(screen.getByRole('button', { name: 'paging' }));

    expect(nextQuery().get('page')).toBe('4');
    expect(nextQuery().get('search')).toBe('каб');
  });

  // Paging and sorting arrive together from the table's single change event.
  it('поважає явно передану сторінку навіть поруч зі зміною сортування', () => {
    renderList('page=7', { both: { page: 2, sortBy: 'amount', sortOrder: 'asc' } });

    fireEvent.click(screen.getByRole('button', { name: 'both' }));

    expect(nextQuery().get('page')).toBe('2');
  });

  it('прибирає з посилання порожній фільтр, а не пише «undefined»', () => {
    renderList('search=каб&ownerId=17', { clear: { search: undefined, ownerId: '' } });

    fireEvent.click(screen.getByRole('button', { name: 'clear' }));

    expect(nextQuery().has('search')).toBe(false);
    expect(nextQuery().has('ownerId')).toBe(false);
  });

  it('повертає посилання до чистого вигляду при скиданні', () => {
    renderList('page=7&search=каб&sortBy=amount', {});

    fireEvent.click(screen.getByRole('button', { name: 'Скинути' }));

    expect(nav.replace).toHaveBeenCalledWith('/deals', { scroll: false });
  });

  it('не додає знак питання, коли не лишилося жодного параметра', () => {
    renderList('search=каб', { clear: { search: undefined } });

    fireEvent.click(screen.getByRole('button', { name: 'clear' }));

    expect(nav.replace).toHaveBeenCalledWith('/deals', { scroll: false });
  });

  it('не гортає сторінку вгору при зміні параметрів', () => {
    renderList('', { paging: { page: 2 } });

    fireEvent.click(screen.getByRole('button', { name: 'paging' }));

    expect(nav.replace.mock.calls.at(-1)?.[1]).toEqual({ scroll: false });
  });
});
