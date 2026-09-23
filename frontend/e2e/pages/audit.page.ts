import { expect, type Locator, type Page } from '@playwright/test';
import { FIRST_LOAD_TIMEOUT } from '../fixtures/test-data';

export class AuditPage {
  constructor(private readonly page: Page) {}

  /**
   * Opens the log narrowed to one record. The list keeps its state in the query
   * string, so a filtered view is just a link — no need to drive the filter row.
   */
  async openForEntity(entityId: string): Promise<void> {
    await this.page.goto(`/audit?entityId=${encodeURIComponent(entityId)}`);
    await expect(this.page.getByRole('heading', { name: 'Аудит' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
  }

  /** Rows whose action column carries the given label. */
  entryWithAction(actionLabel: string): Locator {
    return this.page.getByRole('row').filter({ hasText: actionLabel });
  }
}
