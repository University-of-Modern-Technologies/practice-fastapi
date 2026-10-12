import { describe, expect, it } from 'vitest';
import { DateValue } from './date-value';
import { fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';

describe('DateValue', () => {
  it('додає час на вимогу', () => {
    renderWithProviders(<DateValue value="2026-08-12T15:23:45.123Z" withTime />);
    expect(screen.getByText('12.08.2026 18:23')).toBeInTheDocument();
  });

  it('тримає повний момент у підказці навіть у колонці лише з датою', async () => {
    renderWithProviders(<DateValue value="2026-08-12T15:23:45.123Z" />);

    fireEvent.mouseEnter(screen.getByText('12.08.2026'));

    await waitFor(() => {
      expect(screen.getByRole('tooltip')).toHaveTextContent('12.08.2026 18:23');
    });
  });

  // `expectedCloseDate` is a bare day. Read as an instant it would move to the
  // previous day west of UTC, and its tooltip would invent a midnight.
  it('показує календарну дату як день, без часу й без зсуву', () => {
    renderWithProviders(<DateValue value="2026-09-01" withTime />);

    fireEvent.mouseEnter(screen.getByText('01.09.2026'));

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(screen.queryByText(/00:00/)).not.toBeInTheDocument();
  });
});
