import { describe, expect, it } from 'vitest';
import { PermissionGate } from './permission-gate';
import { renderWithProviders, screen } from '@/test/render';

describe('PermissionGate', () => {
  it('shows the children to a user holding the grant', () => {
    renderWithProviders(
      <PermissionGate resource="contacts" action="read">
        <p>Список контактів</p>
      </PermissionGate>,
      { permissions: ['contacts:read'] },
    );

    expect(screen.getByText('Список контактів')).toBeInTheDocument();
  });

  it('refuses a user whose grant is for another action on the same resource', () => {
    renderWithProviders(
      <PermissionGate resource="contacts" action="delete">
        <p>Видалити</p>
      </PermissionGate>,
      { permissions: ['contacts:read'] },
    );

    expect(screen.queryByText('Видалити')).not.toBeInTheDocument();
    expect(screen.getByText('Недостатньо прав')).toBeInTheDocument();
  });

  it('renders the fallback instead of the refusal notice when one is given', () => {
    renderWithProviders(
      <PermissionGate resource="deals" action="create" fallback={<p>Немає доступу</p>}>
        <button type="button">Створити</button>
      </PermissionGate>,
      { permissions: ['deals:read'] },
    );

    expect(screen.queryByRole('button', { name: 'Створити' })).not.toBeInTheDocument();
    expect(screen.getByText('Немає доступу')).toBeInTheDocument();
  });

  // An empty fallback is a deliberate "show nothing", and it must not fall
  // through to the full-page refusal the way a missing one does.
  it('treats an empty fallback as a request to draw nothing', () => {
    renderWithProviders(
      <PermissionGate resource="deals" action="create" fallback={null}>
        <button type="button">Створити</button>
      </PermissionGate>,
      { permissions: [] },
    );

    expect(screen.queryByText('Недостатньо прав')).not.toBeInTheDocument();
  });

  it('refuses an anonymous caller', () => {
    renderWithProviders(
      <PermissionGate resource="contacts" action="read">
        <p>Список контактів</p>
      </PermissionGate>,
      { user: null },
    );

    expect(screen.getByText('Недостатньо прав')).toBeInTheDocument();
  });
});
