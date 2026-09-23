import { describe, expect, it } from 'vitest';
import { StatusTag } from './status-tag';
import { DEAL_STAGE, ORDER_STATUS } from '@/shared/constants';
import { renderWithProviders, screen } from '@/test/render';

describe('StatusTag', () => {
  it('показує український підпис замість значення з API', () => {
    renderWithProviders(<StatusTag dictionary={DEAL_STAGE} value="QUALIFIED" />);

    expect(screen.getByText('Кваліфіковано')).toBeInTheDocument();
    expect(screen.queryByText('QUALIFIED')).not.toBeInTheDocument();
  });

  it('бере підпис із переданого словника, а не з першого-ліпшого', () => {
    renderWithProviders(<StatusTag dictionary={ORDER_STATUS} value="CANCELLED" />);
    expect(screen.getByText('Скасовано')).toBeInTheDocument();
  });

  it('фарбує успішний і помилковий стани по-різному', () => {
    const { unmount } = renderWithProviders(<StatusTag dictionary={DEAL_STAGE} value="WON" />);
    const won = screen.getByText('Виграно').className;
    unmount();

    renderWithProviders(<StatusTag dictionary={DEAL_STAGE} value="LOST" />);
    expect(screen.getByText('Втрачено').className).not.toBe(won);
  });
});
