import { expect, type Page } from '@playwright/test';
import { FIRST_LOAD_TIMEOUT, cardUrlPattern, idFromUrl } from '../fixtures/test-data';

export interface NewDeal {
  readonly title: string;
  readonly amount: string;
  /** Text typed into the contact picker; the API performs the search. */
  readonly contactQuery: string;
}

export class DealsPage {
  constructor(private readonly page: Page) {}

  async openFromMenu(): Promise<void> {
    await this.page.getByRole('link', { name: 'Угоди', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Угоди' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
  }

  /** Creates a deal linked to a contact and returns the id from the card route. */
  async create(deal: NewDeal): Promise<string> {
    await this.page.getByRole('button', { name: 'Додати угоду', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Нова угода' })).toBeVisible();

    await this.page.getByLabel('Назва', { exact: true }).fill(deal.title);
    await this.page.getByLabel('Сума', { exact: true }).fill(deal.amount);

    const picker = this.page.getByLabel('Контакт', { exact: true });
    await picker.click();
    await picker.fill(deal.contactQuery);
    // The dropdown is portalled to the document body, so it is looked up on the
    // page rather than inside the form.
    await this.page.getByRole('option').filter({ hasText: deal.contactQuery }).first().click();

    await this.page.getByRole('button', { name: 'Створити', exact: true }).click();

    await expect(this.page).toHaveURL(cardUrlPattern('deals'));
    return idFromUrl(this.page.url());
  }

  /**
   * Moves the deal one step along the stage machine. Only the moves the machine
   * allows are offered, so the button carries the label of the target stage.
   */
  async moveToStage(stageLabel: string): Promise<void> {
    await this.page.getByRole('button', { name: stageLabel, exact: true }).click();

    const dialog = this.page.getByRole('dialog').filter({ hasText: 'Змінити стадію' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Перевести', exact: true }).click();
    await expect(dialog).toBeHidden();
  }
}
