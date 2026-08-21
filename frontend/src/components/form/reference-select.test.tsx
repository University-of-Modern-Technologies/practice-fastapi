import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReferenceSelect, type ReferenceOptions } from './reference-select';

interface Row {
  readonly id: string;
  readonly name: string;
}

const ROWS: readonly Row[] = [
  { id: 'a', name: 'Олена Кравець' },
  { id: 'b', name: 'Ігор Мельник' },
];

const label = (row: Row): string => row.name;

/** The trigger antd puts the search input in; clicking it opens the list. */
const openList = (): void => {
  const [root] = document.getElementsByClassName('ant-select');
  if (root === undefined) throw new Error('Селект не відрендерився');
  fireEvent.mouseDown(root);
};

afterEach(() => {
  vi.useRealTimers();
});

describe('ReferenceSelect', () => {
  it('asks the source once for a term that was typed letter by letter', () => {
    vi.useFakeTimers();
    const asked: string[] = [];

    const useOptions = (search: string): ReferenceOptions<Row> => {
      if (asked.at(-1) !== search) asked.push(search);
      return { items: [], isFetching: false };
    };

    render(<ReferenceSelect useOptions={useOptions} getLabel={label} />);
    const input = screen.getByRole('combobox');

    for (const term of ['О', 'Ол', 'Оле', 'Олен']) {
      fireEvent.change(input, { target: { value: term } });
      act(() => {
        vi.advanceTimersByTime(50);
      });
    }

    act(() => {
      vi.advanceTimersByTime(300);
    });

    // The empty first read, then the settled term — not one request per letter.
    expect(asked).toEqual(['', 'Олен']);
  });

  it('names a record the search page does not contain', () => {
    const useOptions = (): ReferenceOptions<Row> => ({ items: ROWS, isFetching: false });
    // The picked record sits on some later page: without a separate read the
    // field would show its identifier and nothing else.
    const useResolved = (id: string | undefined): Row | undefined =>
      id === 'z' ? { id: 'z', name: 'Марія Січ' } : undefined;

    render(
      <ReferenceSelect
        value="z"
        useOptions={useOptions}
        useResolved={useResolved}
        getLabel={label}
      />,
    );

    expect(screen.getByTitle('Марія Січ')).toBeInTheDocument();
  });

  it('tells an empty answer apart from an answer that has not arrived', () => {
    const pending = render(
      <ReferenceSelect
        useOptions={() => ({ items: [], isFetching: true })}
        getLabel={label}
        notFoundText="Нікого не знайдено"
      />,
    );

    openList();
    expect(screen.getByText('Пошук…')).toBeInTheDocument();
    pending.unmount();

    render(
      <ReferenceSelect
        useOptions={() => ({ items: [], isFetching: false })}
        getLabel={label}
        notFoundText="Нікого не знайдено"
      />,
    );

    openList();
    expect(screen.getByText('Нікого не знайдено')).toBeInTheDocument();
  });

  it('hands the caller the picked row, and nothing once the field is cleared', () => {
    const onChange = vi.fn();
    const onSelectRow = vi.fn();
    const useOptions = (): ReferenceOptions<Row> => ({ items: ROWS, isFetching: false });

    const { rerender } = render(
      <ReferenceSelect
        useOptions={useOptions}
        getLabel={label}
        onChange={onChange}
        onSelectRow={onSelectRow}
      />,
    );

    openList();
    fireEvent.click(screen.getByTitle('Ігор Мельник'));

    expect(onChange).toHaveBeenCalledWith('b');
    expect(onSelectRow).toHaveBeenCalledWith(ROWS[1]);

    // The form owns the value, so the cleared state is what it hands back.
    rerender(
      <ReferenceSelect
        value="b"
        useOptions={useOptions}
        getLabel={label}
        onChange={onChange}
        onSelectRow={onSelectRow}
      />,
    );

    const [clear] = document.getElementsByClassName('ant-select-clear');
    if (clear === undefined) throw new Error('Кнопки очищення немає');
    fireEvent.mouseDown(clear);
    fireEvent.click(clear);

    expect(onChange).toHaveBeenLastCalledWith(undefined);
    expect(onSelectRow).toHaveBeenLastCalledWith(undefined);
  });
});
