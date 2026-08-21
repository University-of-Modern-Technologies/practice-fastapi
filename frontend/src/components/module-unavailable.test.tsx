import { describe, expect, it } from 'vitest';
import { ModuleUnavailable } from './module-unavailable';
import { renderWithProviders, screen } from '@/test/render';

describe('ModuleUnavailable', () => {
  it('пояснює відсутній розділ замість того, щоб показати помилку', () => {
    renderWithProviders(
      <ModuleUnavailable missing="звіти аналітики" requirement="аналітика потрібна" />,
    );

    expect(screen.getByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    expect(screen.getByText(/не надає звіти аналітики/)).toBeInTheDocument();
  });

  it('заспокоює щодо решти застосунку', () => {
    renderWithProviders(
      <ModuleUnavailable missing="звіти аналітики" requirement="аналітика потрібна" />,
    );

    expect(screen.getByText(/Решта розділів працює як звичайно/)).toBeInTheDocument();
  });

  it('вставляє в одну й ту саму рамку фрагменти іншого розділу', () => {
    renderWithProviders(
      <ModuleUnavailable
        missing="інтеграції"
        requirement="потрібен обмін із зовнішніми системами"
      />,
    );

    expect(screen.getByText('Розділ недоступний у поточній збірці API')).toBeInTheDocument();
    expect(
      screen.getByText(/не надає інтеграції.+потрібен обмін із зовнішніми системами/),
    ).toBeInTheDocument();
  });
});
