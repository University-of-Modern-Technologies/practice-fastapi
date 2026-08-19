import { describe, expect, it, vi } from 'vitest';
import { DataTable } from './data-table.component';
import type { DataTableColumns } from './data-table.types';
import type { Page } from '@/shared/api';
import type { ListParams, ListParamsPatch } from '@/shared/hooks';
import { fireEvent, renderWithProviders, screen } from '@/test/render';

interface Deal {
  readonly id: string;
  readonly title: string;
  readonly amount: string;
}

type Filters = 'search';

const columns: DataTableColumns<Deal> = [
  { key: 'title', dataIndex: 'title', title: 'Назва' },
  { key: 'amount', dataIndex: 'amount', title: 'Сума', sorter: true },
];

const deal = (id: string, title: string): Deal => ({ id, title, amount: '100.00' });

const pageOf = (items: readonly Deal[], total = items.length): Page<Deal> => ({
  items,
  page: 1,
  pageSize: 20,
  total,
});

const defaultParams: ListParams<Filters> = { page: 1, pageSize: 20 };

interface TableProps {
  readonly page?: Page<Deal> | undefined;
  readonly params?: ListParams<Filters>;
  readonly isLoading?: boolean;
  readonly emptyText?: string;
  readonly emptyAction?: React.ReactNode;
  readonly onParamsChange?: (patch: ListParamsPatch<Filters>) => void;
}

const renderTable = ({
  page = pageOf([deal('1', 'Кабель'), deal('2', 'Розетка')]),
  params = defaultParams,
  isLoading = false,
  emptyText,
  emptyAction,
  onParamsChange = vi.fn(),
}: TableProps = {}): { readonly onParamsChange: (patch: ListParamsPatch<Filters>) => void } => {
  renderWithProviders(
    <DataTable<Deal, Filters>
      tableId="deals-test"
      columns={columns}
      page={page}
      isLoading={isLoading}
      params={params}
      onParamsChange={onParamsChange}
      {...(emptyText === undefined ? {} : { emptyText })}
      {...(emptyAction === undefined ? {} : { emptyAction })}
    />,
  );

  return { onParamsChange };
};

const sortableHeader = (): HTMLElement => screen.getByRole('columnheader', { name: /Сума/ });

const lastPatch = (
  spy: (patch: ListParamsPatch<Filters>) => void,
): ListParamsPatch<Filters> | undefined =>
  (vi.mocked(spy).mock.calls.at(-1)?.[0] ?? undefined) as ListParamsPatch<Filters> | undefined;

describe('DataTable', () => {
  it('показує рядки, які повернув сервер', () => {
    renderTable();

    expect(screen.getByText('Кабель')).toBeInTheDocument();
    expect(screen.getByText('Розетка')).toBeInTheDocument();
  });

  it('рахує сторінки за загальною кількістю з відповіді, а не за довжиною сторінки', () => {
    renderTable({ page: pageOf([deal('1', 'Кабель')], 137) });

    expect(screen.getByText('1–20 з 137')).toBeInTheDocument();
    expect(screen.getByTitle('7')).toBeInTheDocument();
  });

  it('переказує вибрану сторінку словами, а не самими номерами', () => {
    renderTable({ page: pageOf([deal('1', 'Кабель')], 137), params: { page: 3, pageSize: 20 } });

    expect(screen.getByText('41–60 з 137')).toBeInTheDocument();
  });

  // antd speaks `ascend`/`descend`; the API speaks `asc`/`desc`.
  it('перекладає перше сортування колонки в мову API', () => {
    const { onParamsChange } = renderTable();

    fireEvent.click(sortableHeader());

    expect(lastPatch(onParamsChange)).toMatchObject({ sortBy: 'amount', sortOrder: 'asc' });
  });

  it('перекладає зворотне сортування', () => {
    const { onParamsChange } = renderTable({
      params: { page: 1, pageSize: 20, sortBy: 'amount', sortOrder: 'asc' },
    });

    fireEvent.click(sortableHeader());

    expect(lastPatch(onParamsChange)).toMatchObject({ sortBy: 'amount', sortOrder: 'desc' });
  });

  // Leaving `sortBy` behind would keep the API ordering by a column whose
  // arrow is no longer lit.
  it('прибирає обидві половини сортування, коли його скинули', () => {
    const { onParamsChange } = renderTable({
      params: { page: 1, pageSize: 20, sortBy: 'amount', sortOrder: 'desc' },
    });

    fireEvent.click(sortableHeader());

    expect(lastPatch(onParamsChange)).toMatchObject({ sortBy: undefined, sortOrder: undefined });
  });

  it('показує в заголовку те сортування, яке прийшло з посилання', () => {
    renderTable({ params: { page: 1, pageSize: 20, sortBy: 'amount', sortOrder: 'desc' } });

    expect(sortableHeader()).toHaveAttribute('aria-sort', 'descending');
  });

  it('не запалює стрілку на колонці, за якою не сортують', () => {
    renderTable({ params: { page: 1, pageSize: 20, sortBy: 'createdAt', sortOrder: 'desc' } });

    expect(sortableHeader()).not.toHaveAttribute('aria-sort');
  });

  it('гортає сторінки, не чіпаючи решти параметрів', () => {
    const { onParamsChange } = renderTable({
      page: pageOf([deal('1', 'Кабель')], 137),
      params: { page: 1, pageSize: 20, search: 'каб' },
    });

    fireEvent.click(screen.getByTitle('2'));

    const patch = lastPatch(onParamsChange);
    expect(patch).toMatchObject({ page: 2 });
    expect(patch).not.toHaveProperty('search');
  });

  it('пояснює порожній список своїми словами, а не «No data»', () => {
    renderTable({ page: pageOf([]), emptyText: 'Угод ще немає' });

    expect(screen.getByText('Угод ще немає')).toBeInTheDocument();
  });

  it('пропонує в порожньому списку дію, якою його заповнити', () => {
    renderTable({
      page: pageOf([]),
      emptyText: 'Угод ще немає',
      emptyAction: <button type="button">Створити угоду</button>,
    });

    expect(screen.getByRole('button', { name: 'Створити угоду' })).toBeInTheDocument();
  });

  // The first read is not an empty list: saying "нічого немає" before the
  // answer arrives is a claim the table cannot yet make.
  it('мовчить про порожнечу, поки триває перше читання', () => {
    renderTable({ page: undefined, isLoading: true, emptyText: 'Угод ще немає' });

    expect(screen.queryByText('Угод ще немає')).not.toBeInTheDocument();
  });

  it('відкриває рядок за кліком, коли є куди відкривати', () => {
    const onRowClick = vi.fn();
    renderWithProviders(
      <DataTable<Deal, Filters>
        tableId="deals-test"
        columns={columns}
        page={pageOf([deal('1', 'Кабель')])}
        isLoading={false}
        params={defaultParams}
        onParamsChange={vi.fn()}
        onRowClick={onRowClick}
      />,
    );

    fireEvent.click(screen.getByText('Кабель'));

    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: '1' }));
  });

  it('ставить панель фільтрів над таблицею', () => {
    renderWithProviders(
      <DataTable<Deal, Filters>
        tableId="deals-test"
        columns={columns}
        page={pageOf([deal('1', 'Кабель')])}
        isLoading={false}
        params={defaultParams}
        onParamsChange={vi.fn()}
        filters={<span>Фільтри</span>}
        toolbar={<button type="button">Створити</button>}
      />,
    );

    expect(screen.getByText('Фільтри')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Створити' })).toBeInTheDocument();
  });
});
