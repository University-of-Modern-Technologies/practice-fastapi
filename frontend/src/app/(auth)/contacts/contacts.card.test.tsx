import { describe, expect, it, vi } from 'vitest';
import type * as ApiModule from '@/shared/api';
import { act, fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';
import ContactPage from './[id]/page';
import { contactsKeys } from './contacts.queries';
import type { Contact } from './contacts.types';

const CONTACT_ID = '22222222-2222-2222-2222-222222222222';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => `/contacts/${CONTACT_ID}`,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: CONTACT_ID }),
}));

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return {
    ...actual,
    http: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  };
});

const { http } = await import('@/shared/api');

const contact = (overrides: Partial<Contact> = {}): Contact => ({
  id: CONTACT_ID,
  ownerId: '00000000-0000-0000-0000-000000000001',
  firstName: 'Олена',
  lastName: 'Ковальчук',
  email: 'olena@example.com',
  phone: null,
  company: null,
  notes: null,
  createdAt: '2026-08-01T10:00:00.000Z',
  updatedAt: '2026-08-01T10:00:00.000Z',
  ...overrides,
});

describe('Картка контакту — що йде в PATCH', () => {
  // The diff used to be taken against whatever the cache held at save time. A
  // fresher copy with someone else's e-mail made the untouched field look
  // "changed back", and the save reverted their edit.
  it('надсилає лише змінене користувачем, навіть якщо кеш тим часом оновився', async () => {
    vi.mocked(http.get).mockResolvedValue(contact());
    vi.mocked(http.patch).mockResolvedValue(
      contact({ email: 'new@example.com', phone: '+380501234567' }),
    );
    const { queryClient } = renderWithProviders(<ContactPage />, {
      permissions: ['contacts:read', 'contacts:write'],
    });

    const phone = (await screen.findByLabelText('Телефон')) as HTMLInputElement;
    fireEvent.change(phone, { target: { value: '+380501234567' } });

    // Another user changed the e-mail; the card's query picks it up.
    act(() => {
      queryClient.setQueryData(
        contactsKeys.detail(CONTACT_ID),
        contact({ email: 'new@example.com' }),
      );
    });

    fireEvent.click(screen.getByRole('button', { name: 'Зберегти' }));

    await waitFor(() => expect(http.patch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(http.patch).mock.calls[0]?.[1]).toEqual({ phone: '+380501234567' });
  });
});
