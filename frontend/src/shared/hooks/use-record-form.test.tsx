import { Form, Input } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import { useRecordForm } from './use-record-form';
import { ConflictAlert } from '@/components/conflict-alert';
import { act, fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';

interface Note {
  readonly id: string;
  readonly title: string;
  /** Not on the form: a change here alone must not stop a save. */
  readonly status: string;
  readonly version?: number | undefined;
}

interface NoteValues {
  readonly title?: string | undefined;
}

const toNoteValues = (note: Note): Partial<NoteValues> => ({ title: note.title });

const note = (overrides: Partial<Note> = {}): Note => ({
  id: 'n-1',
  title: 'Перша назва',
  status: 'OPEN',
  version: 1,
  ...overrides,
});

type Reload = () => Promise<{ readonly data?: Note; readonly isError?: boolean }>;

/** What a save would send: the snapshot's version and the field's current value. */
interface Sent {
  readonly version: number | undefined;
  readonly title: unknown;
  /** The snapshot's own title — what a field-by-field diff compares with. */
  readonly baseTitle: string | undefined;
}

const sent = vi.fn<(payload: Sent) => void>();

function Probe({ record, onReload }: { readonly record: Note; readonly onReload?: Reload }) {
  const [form] = Form.useForm<NoteValues>();
  const { base, markDirty, hasConflict, reload } = useRecordForm({
    form,
    record,
    toValues: toNoteValues,
    onReload,
  });

  return (
    <>
      <ConflictAlert open={hasConflict} onReload={reload} />
      <Form form={form} initialValues={toNoteValues(record)} onValuesChange={markDirty}>
        <Form.Item name="title" label="Назва">
          <Input />
        </Form.Item>
      </Form>
      <button
        type="button"
        onClick={() =>
          sent({
            version: base?.version,
            title: form.getFieldValue('title'),
            baseTitle: base?.title,
          })
        }
      >
        Зберегти
      </button>
    </>
  );
}

const field = (): HTMLInputElement => screen.getByLabelText('Назва') as HTMLInputElement;

const type = (value: string): void => {
  fireEvent.change(field(), { target: { value } });
};

const save = (): Sent => {
  sent.mockClear();
  fireEvent.click(screen.getByRole('button', { name: 'Зберегти' }));
  const payload = sent.mock.calls[0]?.[0];
  if (!payload) throw new Error('nothing was saved');
  return payload;
};

const conflictShown = (): boolean => screen.queryByText('Запис змінив інший користувач') !== null;

describe('useRecordForm', () => {
  it('показує свіжу копію, коли користувач нічого не вводив', async () => {
    const { rerender } = renderWithProviders(<Probe record={note()} />);

    rerender(<Probe record={note({ title: 'Нова назва', version: 2 })} />);

    await waitFor(() => expect(field().value).toBe('Нова назва'));
    expect(save()).toMatchObject({ version: 2, title: 'Нова назва' });
    expect(conflictShown()).toBe(false);
  });

  // The defect this hook exists for: the version moved on, the values did not,
  // and the next save wrote the stale values under the fresh version.
  it('не підміняє версію під незбереженими правками, якщо запис змінили', async () => {
    const { rerender } = renderWithProviders(<Probe record={note()} />);
    type('Моя назва');

    rerender(<Probe record={note({ title: 'Чужа назва', version: 2 })} />);

    expect(await screen.findByText('Запис змінив інший користувач')).toBeInTheDocument();
    expect(field().value).toBe('Моя назва');
    // The save still carries the version the user edited, so it answers 409
    // instead of overwriting the other person's title.
    expect(save()).toMatchObject({ version: 1, title: 'Моя назва', baseTitle: 'Перша назва' });
  });

  it('бере нову версію, якщо на сервері не змінилося нічого з того, що редагує форма', () => {
    const { rerender } = renderWithProviders(<Probe record={note()} />);
    type('Моя назва');

    rerender(<Probe record={note({ status: 'CLOSED', version: 2 })} />);

    expect(conflictShown()).toBe(false);
    expect(save()).toMatchObject({ version: 2, title: 'Моя назва' });
  });

  it('після «Перечитати» показує поточні значення разом із поточною версією', async () => {
    const fresh = note({ title: 'Чужа назва', version: 2 });
    const onReload = vi.fn<Reload>().mockResolvedValue({ data: fresh });
    const { rerender } = renderWithProviders(<Probe record={note()} onReload={onReload} />);
    type('Моя назва');
    rerender(<Probe record={fresh} onReload={onReload} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Перечитати' }));

    await waitFor(() => expect(field().value).toBe('Чужа назва'));
    expect(conflictShown()).toBe(false);
    expect(save()).toMatchObject({ version: 2, title: 'Чужа назва', baseTitle: 'Чужа назва' });
  });

  it('лишає пояснення, якщо перечитати не вдалося', async () => {
    const onReload = vi.fn<Reload>().mockResolvedValue({ data: note(), isError: true });
    const { rerender } = renderWithProviders(<Probe record={note()} onReload={onReload} />);
    type('Моя назва');
    rerender(<Probe record={note({ title: 'Чужа назва', version: 2 })} onReload={onReload} />);

    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'Перечитати' }));
    });

    expect(conflictShown()).toBe(true);
    expect(field().value).toBe('Моя назва');
    expect(save().version).toBe(1);
  });

  // Contacts carry no version: they are diffed field by field, so the diff has
  // to be taken against the copy the user edited — never against a fresher one.
  it('для запису без версії тримає знімок, з яким працював користувач', () => {
    const { rerender } = renderWithProviders(<Probe record={note({ version: undefined })} />);
    type('Моя назва');

    rerender(<Probe record={note({ title: 'Чужа назва', version: undefined })} />);

    expect(conflictShown()).toBe(false);
    expect(field().value).toBe('Моя назва');
    expect(save().baseTitle).toBe('Перша назва');
  });
});
