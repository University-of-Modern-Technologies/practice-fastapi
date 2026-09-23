import { expect, type Page } from '@playwright/test';
import { FIRST_LOAD_TIMEOUT, cardUrlPattern, idFromUrl } from '../fixtures/test-data';

export interface NewOrder {
  readonly contactId: string;
  readonly dealId: string;
  readonly sku: string;
  readonly quantity: number;
}

export class OrdersPage {
  constructor(private readonly page: Page) {}

  async openFromMenu(): Promise<void> {
    await this.page.getByRole('link', { name: 'Замовлення', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Замовлення' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
  }

  /**
   * Creates a draft with one line. The references are typed as identifiers
   * because that is what the form asks for; they come from the two records the
   * scenario has already made.
   */
  async create(order: NewOrder): Promise<string> {
    await this.page.getByRole('button', { name: 'Створити замовлення', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Нове замовлення' })).toBeVisible();

    await this.page.getByLabel('Контакт (ID)').fill(order.contactId);
    await this.page.getByLabel('Угода (ID)').fill(order.dealId);

    await this.addItem(order.sku, order.quantity);

    await this.page.getByRole('button', { name: 'Створити', exact: true }).click();

    await expect(this.page).toHaveURL(cardUrlPattern('orders'));
    return idFromUrl(this.page.url());
  }

  /** Adds a catalogue position to the order being edited. */
  async addItem(sku: string, quantity: number): Promise<void> {
    // The card shows the button twice — beside the heading and inside the empty
    // state — and both open the same dialog.
    await this.page.getByRole('button', { name: 'Додати позицію', exact: true }).first().click();

    const dialog = this.page.getByRole('dialog').filter({ hasText: 'Додати позицію' });
    await expect(dialog).toBeVisible();

    const product = dialog.getByLabel('Товар', { exact: true });
    await product.click();
    await product.fill(sku);
    // The catalogue dropdown is portalled to the document body.
    await this.page.getByRole('option').filter({ hasText: sku }).first().click();

    await dialog.getByLabel('Кількість', { exact: true }).fill(String(quantity));
    await dialog.getByRole('button', { name: 'Додати', exact: true }).click();
    await expect(dialog).toBeHidden();
  }

  /**
   * Moves the order along the status machine. Confirming reserves stock and
   * fulfilling writes it off, so each call here has a consequence in the
   * warehouse the scenario checks afterwards.
   */
  async changeStatus(statusLabel: string): Promise<void> {
    await this.page.getByRole('button', { name: 'Змінити статус', exact: true }).click();

    const dialog = this.page.getByRole('dialog').filter({ hasText: 'Зміна статусу' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('radio', { name: statusLabel, exact: true }).check();
    await dialog.getByRole('button', { name: 'Змінити статус', exact: true }).click();
    await expect(dialog).toBeHidden();

    await expect(this.page.getByText(statusLabel, { exact: true }).first()).toBeVisible();
  }
}
