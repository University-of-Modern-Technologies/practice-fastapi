import { describe, expect, it } from 'vitest';
import { useMutationFeedback, type DomainMessages } from './use-mutation-feedback';
import { ApiError } from '@/shared/api';
import { fireEvent, renderWithProviders, screen, waitFor } from '@/test/render';

const STOCK_MESSAGES: DomainMessages = {
  INSUFFICIENT_STOCK: 'Недостатньо залишку на складі',
  ORDER_ALREADY_CONFIRMED: 'Замовлення вже підтверджено',
};

interface ProbeProps {
  readonly error?: unknown;
  readonly messages?: DomainMessages;
}

function FeedbackProbe({ error, messages }: ProbeProps) {
  const { reportSuccess, reportFailure, reportFailureWith } = useMutationFeedback();

  /**
   * The declared type is the one TanStack calls `onError` with. If the reporter
   * ever grew a second required parameter, this assignment would stop compiling
   * — which is exactly when a module would start passing the mutation variables
   * into it by accident.
   */
  const onError: (error: unknown, variables: { readonly id: string }, context: unknown) => void =
    reportFailure;

  return (
    <div>
      <button type="button" onClick={() => reportSuccess('Збережено')}>
        Зберегти
      </button>
      <button type="button" onClick={() => onError(error, { id: '17' }, undefined)}>
        Помилка
      </button>
      <button type="button" onClick={() => reportFailureWith(messages ?? STOCK_MESSAGES)(error)}>
        Доменна помилка
      </button>
    </div>
  );
}

const click = (name: string): void => {
  fireEvent.click(screen.getByRole('button', { name }));
};

const expectShown = async (text: string | RegExp): Promise<void> => {
  await waitFor(() => {
    expect(screen.getByText(text)).toBeInTheDocument();
  });
};

const apiError = (status: number, code: string, requestId: string | null = null): ApiError =>
  new ApiError({ status, code, message: `HTTP ${status}`, requestId });

describe('useMutationFeedback', () => {
  it('підтверджує вдалий запис коротким повідомленням', async () => {
    renderWithProviders(<FeedbackProbe />);

    click('Зберегти');

    await expectShown('Збережено');
  });

  it('пояснює відмову за статусом, а не мовчить', async () => {
    renderWithProviders(<FeedbackProbe error={apiError(403, 'FORBIDDEN')} />);

    click('Помилка');

    await expectShown('Недостатньо прав для цієї дії');
  });

  it('переживає другий аргумент, який TanStack передає в onError', async () => {
    renderWithProviders(<FeedbackProbe error={apiError(404, 'NOT_FOUND')} />);

    click('Помилка');

    await expectShown('Запис не знайдено');
  });

  it('додає ідентифікатор запиту, щоб повідомлення можна було знайти в логах', async () => {
    renderWithProviders(<FeedbackProbe error={apiError(500, 'INTERNAL', 'req-42')} />);

    click('Помилка');

    await expectShown('ID запиту: req-42');
  });

  it('не приховує помилку, яка навіть не з API', async () => {
    renderWithProviders(<FeedbackProbe error={new TypeError('boom')} />);

    click('Помилка');

    await expectShown('Сталася непередбачена помилка');
  });

  // "Недостатньо залишку на складі" tells the operator what to do next; the
  // generic sentence for the same status does not.
  it('обирає доменне речення за кодом помилки', async () => {
    renderWithProviders(<FeedbackProbe error={apiError(409, 'INSUFFICIENT_STOCK')} />);

    click('Доменна помилка');

    await expectShown('Недостатньо залишку на складі');
  });

  it('розрізняє два різні коди в межах одного статусу', async () => {
    renderWithProviders(<FeedbackProbe error={apiError(409, 'ORDER_ALREADY_CONFIRMED')} />);

    click('Доменна помилка');

    await expectShown('Замовлення вже підтверджено');
    expect(screen.queryByText('Недостатньо залишку на складі')).not.toBeInTheDocument();
  });

  it('повертається до загального пояснення, коли код невідомий', async () => {
    renderWithProviders(<FeedbackProbe error={apiError(409, 'DEAL_CONCURRENT_MODIFICATION')} />);

    click('Доменна помилка');

    await expectShown('Дію відхилено через поточний стан даних');
  });

  it('повертається до загального пояснення й для помилки поза API', async () => {
    renderWithProviders(<FeedbackProbe error={new Error('boom')} />);

    click('Доменна помилка');

    await expectShown('Сталася непередбачена помилка');
  });
});
