import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { useVersionConflict } from './use-version-conflict';
import { ConflictAlert } from '@/components/conflict-alert';
import { ApiError } from '@/shared/api';
import { fireEvent, renderWithProviders, screen } from '@/test/render';

function ConflictProbe({ error }: { readonly error: unknown }) {
  const { hasConflict, handleError, clearConflict } = useVersionConflict();
  const [handled, setHandled] = useState<boolean | null>(null);

  return (
    <div>
      <ConflictAlert open={hasConflict} onReload={clearConflict} />
      <p data-testid="handled">{String(handled)}</p>
      <button type="button" onClick={() => setHandled(handleError(error))}>
        Зберегти
      </button>
    </div>
  );
}

/** Whether the save handler considered the error its own to display. */
const handled = (): string => screen.getByTestId('handled').textContent ?? '';

const apiError = (status: number, code: string): ApiError =>
  new ApiError({ status, code, message: `HTTP ${status}` });

const save = (): void => {
  fireEvent.click(screen.getByRole('button', { name: 'Зберегти' }));
};

const conflictShown = (): boolean => screen.queryByText('Запис змінив інший користувач') !== null;

describe('useVersionConflict', () => {
  it('показує окреме пояснення й пропонує перечитати запис', () => {
    renderWithProviders(<ConflictProbe error={apiError(409, 'DEAL_CONCURRENT_MODIFICATION')} />);

    save();

    expect(conflictShown()).toBe(true);
    expect(screen.getByRole('button', { name: 'Перечитати' })).toBeInTheDocument();
  });

  it('нічого не показує, поки збереження не впало', () => {
    renderWithProviders(<ConflictProbe error={apiError(409, 'DEAL_CONCURRENT_MODIFICATION')} />);

    expect(conflictShown()).toBe(false);
  });

  it('лишає помилку валідації тому, хто вміє показати її на полі', () => {
    renderWithProviders(<ConflictProbe error={apiError(422, 'VALIDATION_ERROR')} />);

    save();

    expect(handled()).toBe('false');
    expect(conflictShown()).toBe(false);
  });

  it('не бере на себе відмову в доступі', () => {
    renderWithProviders(<ConflictProbe error={apiError(403, 'FORBIDDEN')} />);

    save();

    expect(conflictShown()).toBe(false);
  });

  it('не бере на себе помилку, яка навіть не з API', () => {
    renderWithProviders(<ConflictProbe error={new TypeError('boom')} />);

    save();

    expect(handled()).toBe('false');
    expect(conflictShown()).toBe(false);
  });

  /**
   * The hook branches on the status alone, and not every 409 is a lost race:
   * an entity without `version` answers 409 for a refused transition too, and
   * for that error "someone else changed the record" is the wrong sentence.
   * The limitation is asserted rather than described, so the day the hook
   * starts reading the code, this case fails and says where to look.
   */
  it('вважає конфліктом версії будь-який 409 — навіть відмову домену', () => {
    renderWithProviders(<ConflictProbe error={apiError(409, 'ORDER_ALREADY_CONFIRMED')} />);

    save();

    expect(handled()).toBe('true');
    expect(conflictShown()).toBe(true);
  });

  it('прибирає пояснення після перечитування', () => {
    renderWithProviders(<ConflictProbe error={apiError(409, 'ORDER_CONCURRENT_MODIFICATION')} />);

    save();
    fireEvent.click(screen.getByRole('button', { name: 'Перечитати' }));

    expect(conflictShown()).toBe(false);
  });
});
