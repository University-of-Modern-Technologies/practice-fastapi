import { describe, expect, it } from 'vitest';
import { PermissionGate } from './permission-gate';
import { canActOn } from '@/shared/hooks';
import { grants, renderWithProviders, screen, testUser } from '@/test/render';

const ME = '00000000-0000-0000-0000-000000000001';
const SOMEONE_ELSE = '00000000-0000-0000-0000-000000000002';

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

  // `deals:write OWN` next to `deals:read ALL` is an ordinary role: it sees
  // every deal and may change only its own. Offering the button on someone
  // else's deal only leads to a 403.
  it('hides a control on somebody else’s record when the grant is OWN', () => {
    renderWithProviders(
      <PermissionGate resource="deals" action="write" ownerId={SOMEONE_ELSE} fallback={null}>
        <button type="button">Зберегти</button>
      </PermissionGate>,
      { user: testUser({ id: ME, permissions: grants(['deals:write'], 'OWN') }) },
    );

    expect(screen.queryByRole('button', { name: 'Зберегти' })).not.toBeInTheDocument();
  });

  it('shows the same control on the caller’s own record', () => {
    renderWithProviders(
      <PermissionGate resource="deals" action="write" ownerId={ME} fallback={null}>
        <button type="button">Зберегти</button>
      </PermissionGate>,
      { user: testUser({ id: ME, permissions: grants(['deals:write'], 'OWN') }) },
    );

    expect(screen.getByRole('button', { name: 'Зберегти' })).toBeInTheDocument();
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

describe('canActOn', () => {
  it('lets ALL act on any record', () => {
    expect(canActOn('ALL', ME, SOMEONE_ELSE)).toBe(true);
    expect(canActOn('ALL', ME, null)).toBe(true);
  });

  it('limits OWN to the caller’s own records, and an unowned one is not theirs', () => {
    expect(canActOn('OWN', ME, ME)).toBe(true);
    expect(canActOn('OWN', ME, SOMEONE_ELSE)).toBe(false);
    expect(canActOn('OWN', ME, null)).toBe(false);
  });

  it('judges only the grant when there is no record yet', () => {
    expect(canActOn('OWN', ME, undefined)).toBe(true);
    expect(canActOn(null, ME, undefined)).toBe(false);
  });
});
