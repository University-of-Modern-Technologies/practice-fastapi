import { expect, type Locator, type Page } from '@playwright/test';
import { FIRST_LOAD_TIMEOUT } from '../fixtures/test-data';

/** The sign-in form. Fields are addressed by the labels the operator reads. */
export class LoginPage {
  constructor(private readonly page: Page) {}

  get submitButton(): Locator {
    return this.page.getByRole('button', { name: 'Увійти', exact: true });
  }

  async open(): Promise<void> {
    await this.page.goto('/login');
    // The very first navigation waits on a container that may still be warming up.
    await expect(this.submitButton).toBeVisible({ timeout: FIRST_LOAD_TIMEOUT });
  }

  async signIn(email: string, password: string): Promise<void> {
    await this.page.getByLabel('Пошта').fill(email);
    await this.page.getByLabel('Пароль').fill(password);
    await this.submitButton.click();
  }
}
