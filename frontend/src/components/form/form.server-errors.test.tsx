import { Form, Input } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import { applyServerErrors } from './form.server-errors';
import { ApiError } from '@/shared/api';
import { fireEvent, renderWithProviders, screen, within } from '@/test/render';

const validationError = (details: unknown): ApiError =>
  new ApiError({
    status: 422,
    code: 'VALIDATION_ERROR',
    message: 'Перевірте введені дані',
    details,
  });

const bodyErrors = (...messages: readonly string[]): ApiError =>
  validationError({ fieldErrors: { body: messages } });

const applied = vi.fn<(handled: boolean) => void>();

/** A form with the two fields the API is expected to answer about. */
const Harness = ({ error }: { readonly error: unknown }) => {
  const [form] = Form.useForm();

  return (
    <Form form={form} layout="vertical">
      <Form.Item name="firstName" label="Імʼя">
        <Input />
      </Form.Item>
      <Form.Item name="email" label="Пошта">
        <Input />
      </Form.Item>
      <button type="button" onClick={() => applied(applyServerErrors(form, error))}>
        Зберегти
      </button>
    </Form>
  );
};

const save = (error: unknown): void => {
  renderWithProviders(<Harness error={error} />);
  fireEvent.click(screen.getByRole('button', { name: 'Зберегти' }));
};

/** The block antd draws around one field: label, control and its message. */
const itemOf = (label: string): HTMLElement => {
  const item = screen.getByText(label).closest('.ant-form-item');
  if (item === null) throw new Error(`Поля «${label}» немає на формі`);
  return item as HTMLElement;
};

describe('applyServerErrors', () => {
  it('кладе повідомлення на поле, назване в шляху', async () => {
    save(bodyErrors('body.firstName: Занадто коротке значення'));

    expect(await within(itemOf('Імʼя')).findByText('Занадто коротке значення')).toBeInTheDocument();
    expect(within(itemOf('Пошта')).queryByText('Занадто коротке значення')).not.toBeInTheDocument();
    expect(applied).toHaveBeenCalledWith(true);
  });

  it('розводить два повідомлення по різних полях', async () => {
    save(bodyErrors('body.firstName: Обовʼязкове поле', 'body.email: Некоректна адреса'));

    expect(await within(itemOf('Імʼя')).findByText('Обовʼязкове поле')).toBeInTheDocument();
    expect(await within(itemOf('Пошта')).findByText('Некоректна адреса')).toBeInTheDocument();
  });

  // The generic notification is the only place left where the user can read
  // this message, so claiming it was placed would lose it entirely.
  it('не привласнює повідомлення про поле, якого на формі немає', () => {
    save(bodyErrors('body.nickname: Занадто довге значення'));

    expect(applied).toHaveBeenCalledWith(false);
  });

  it('віддає решту повідомлень нагору, якщо хоч одне не знайшло поля', async () => {
    save(bodyErrors('body.firstName: Обовʼязкове поле', 'body.nickname: Занадто довге значення'));

    expect(await within(itemOf('Імʼя')).findByText('Обовʼязкове поле')).toBeInTheDocument();
    expect(applied).toHaveBeenCalledWith(false);
  });

  it('лишає загальному повідомленню помилку без назви поля', () => {
    save(bodyErrors('Тіло запиту завелике'));

    expect(applied).toHaveBeenCalledWith(false);
  });

  it('не забирає собі помилку, що не є валідацією', () => {
    save(new ApiError({ status: 409, code: 'DEAL_CONCURRENT_MODIFICATION', message: 'Конфлікт' }));

    expect(applied).toHaveBeenCalledWith(false);
  });

  it.each([
    ['деталі не є обʼєктом', validationError('щось пішло не так')],
    ['деталей немає зовсім', validationError(undefined)],
    ['перелік помилок не є масивом', validationError({ fieldErrors: { body: 'Занадто коротке' } })],
    ['помилка не з API', new Error('boom')],
  ])('не падає, коли %s', (_name, error) => {
    expect(() => save(error)).not.toThrow();
    expect(applied).toHaveBeenCalledWith(false);
  });
});
