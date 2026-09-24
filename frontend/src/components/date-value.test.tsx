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
});
