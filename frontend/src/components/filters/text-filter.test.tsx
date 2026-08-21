import { describe, expect, it, vi } from 'vitest';
import { TextFilter } from './text-filter';
import { fireEvent, renderWithProviders, screen } from '@/test/render';

const ENTER = { key: 'Enter', code: 'Enter', keyCode: 13, charCode: 13 };

const field = (): HTMLElement => screen.getByRole('searchbox');

const typeInto = (text: string): void => {
  fireEvent.change(field(), { target: { value: text } });
};

describe('TextFilter', () => {
  it('показує те, за чим список уже відфільтровано', () => {
    renderWithProviders(<TextFilter value="кабель" onCommit={vi.fn()} />);

    expect(field()).toHaveValue('кабель');
  });

  it('підказує, що це поле пошуку', () => {
    renderWithProviders(
      <TextFilter value={undefined} onCommit={vi.fn()} placeholder="Пошук угод" />,
    );

    expect(screen.getByPlaceholderText('Пошук угод')).toBeInTheDocument();
  });

  // A request per keystroke puts the list on every prefix of the word, and the
  // answer to "Ale" is noise on the way to "Alex".
  it('мовчить, поки користувач друкує', () => {
    const onCommit = vi.fn();
    renderWithProviders(<TextFilter value={undefined} onCommit={onCommit} />);

    typeInto('к');
    typeInto('ка');
    typeInto('каб');

    expect(onCommit).not.toHaveBeenCalled();
  });

  it('застосовує пошук за Enter', () => {
    const onCommit = vi.fn();
    renderWithProviders(<TextFilter value={undefined} onCommit={onCommit} />);

    typeInto('кабель');
    fireEvent.keyDown(field(), ENTER);

    expect(onCommit).toHaveBeenCalledWith('кабель');
  });

  it('застосовує пошук, коли фокус пішов з поля', () => {
    const onCommit = vi.fn();
    renderWithProviders(<TextFilter value={undefined} onCommit={onCommit} />);

    typeInto('кабель');
    fireEvent.blur(field());

    expect(onCommit).toHaveBeenCalledWith('кабель');
  });

  it('прибирає випадкові пробіли по краях запиту', () => {
    const onCommit = vi.fn();
    renderWithProviders(<TextFilter value={undefined} onCommit={onCommit} />);

    typeInto('  кабель  ');
    fireEvent.blur(field());

    expect(onCommit).toHaveBeenCalledWith('кабель');
  });

  // An empty filter has to leave the query string rather than sit there as an
  // empty value the list still carries in its link.
  it('віддає порожній запит як відсутній фільтр', () => {
    const onCommit = vi.fn();
    renderWithProviders(<TextFilter value="кабель" onCommit={onCommit} />);

    typeInto('   ');
    fireEvent.blur(field());

    expect(onCommit).toHaveBeenCalledWith(undefined);
  });

  it('не перезапитує список, коли значення не змінилося', () => {
    const onCommit = vi.fn();
    renderWithProviders(<TextFilter value="кабель" onCommit={onCommit} />);

    fireEvent.keyDown(field(), ENTER);
    fireEvent.blur(field());

    expect(onCommit).not.toHaveBeenCalled();
  });

  // Enter applies the filter, the list re-renders with it, and the blur that
  // follows must not send the very same request a second time.
  it('не повторює запит, коли після Enter фокус іде з поля', () => {
    const onCommit = vi.fn();
    const { rerender } = renderWithProviders(<TextFilter value={undefined} onCommit={onCommit} />);

    typeInto('кабель');
    fireEvent.keyDown(field(), ENTER);
    rerender(<TextFilter value="кабель" onCommit={onCommit} />);
    fireEvent.blur(field());

    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it('підхоплює значення, змінене ззовні — скиданням фільтрів або посиланням', () => {
    const { rerender } = renderWithProviders(<TextFilter value="кабель" onCommit={vi.fn()} />);

    rerender(<TextFilter value={undefined} onCommit={vi.fn()} />);

    expect(field()).toHaveValue('');
  });
});
