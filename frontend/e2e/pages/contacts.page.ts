import { expect, type Page } from '@playwright/test';
import { FIRST_LOAD_TIMEOUT, cardUrlPattern, idFromUrl } from '../fixtures/test-data';

export interface NewContact {
  readonly lastName: string;
  readonly firstName: string;
  readonly email: string;
}

export class ContactsPage {
  constructor(private readonly page: Page) {}

  /** Navigates the way an operator does — through the sidebar. */
  async openFromMenu(): Promise<void> {
    await this.page.getByRole('link', { name: 'Контакти', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Контакти' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
  }

  /** Fills the create form and returns the id of the record the API assigned. */
  async create(contact: NewContact): Promise<string> {
    await this.page.getByRole('button', { name: 'Новий контакт', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Новий контакт' })).toBeVisible();

    await this.page.getByLabel('Прізвище').fill(contact.lastName);
    await this.page.getByLabel('Імʼя').fill(contact.firstName);
    await this.page.getByLabel('Пошта').fill(contact.email);
    await this.page.getByRole('button', { name: 'Створити', exact: true }).click();

    // A successful create lands on the card, so the identifier arrives in the URL.
    await expect(this.page).toHaveURL(cardUrlPattern('contacts'));
    return idFromUrl(this.page.url());
  }
}
