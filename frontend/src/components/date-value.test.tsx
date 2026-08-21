import { describe, expect, it } from 'vitest';
import { DateValue } from './date-value';
import { fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';

describe('DateValue', () => {
  it('показує дату в форматі, звичному для користувача', () => {
    renderWithProviders(<DateValue value="2026-08-12T15:23:45.123Z" />);
    expect(screen.getByText('12.08.2026')).toBeInTheDocument();
  });

  it('додає час на вимогу', () => {
    renderWithProviders(<DateValue value="2026-08-12T15:23:45.123Z" withTime />);
    expect(screen.getByText('12.08.2026 18:23')).toBeInTheDocument();
  });

  // The zone is fixed to Europe/Kyiv rather than taken from the browser: the
  // page is rendered on the server first, and two different clock times for the
  // same instant would be a hydration mismatch on every timestamp in a table.
  it('читає момент у київському часі, а не в UTC', () => {
    renderWithProviders(<DateValue value="2026-08-12T22:30:00.000Z" withTime />);
    expect(screen.getByText('13.08.2026 01:30')).toBeInTheDocument();
  });

  it('не зсуває календарну дату, яка приходить без зони', () => {
    renderWithProviders(<DateValue value="2026-08-12" />);
    expect(screen.getByText('12.08.2026')).toBeInTheDocument();
  });

  it('показує прочерк замість «Invalid Date», коли значення немає', () => {
    renderWithProviders(<DateValue value={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('показує прочерк для непридатного значення', () => {
    renderWithProviders(<DateValue value="не дата" />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('тримає повний момент у підказці навіть у колонці лише з датою', async () => {
    renderWithProviders(<DateValue value="2026-08-12T15:23:45.123Z" />);

    fireEvent.mouseEnter(screen.getByText('12.08.2026'));

    await waitFor(() => {
      expect(screen.getByRole('tooltip')).toHaveTextContent('12.08.2026 18:23');
    });
  });
});
