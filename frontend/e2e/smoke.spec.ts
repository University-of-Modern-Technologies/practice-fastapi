import { expect, test, type Page } from '@playwright/test';
import {
  CENTRAL_WAREHOUSE_CODE,
  FIRST_LOAD_TIMEOUT,
  ORDER_ITEM_QUANTITY,
  SEED_PRODUCT_SKU,
  cardUrlPattern,
  idFromUrl,
  runData,
} from './fixtures/test-data';
import { AuditPage } from './pages/audit.page';
import { ContactsPage } from './pages/contacts.page';
import { DealsPage } from './pages/deals.page';
import { OrdersPage } from './pages/orders.page';

interface StockRow {
  readonly onHand: number;
  readonly reserved: number;
}

/**
 * Column order of the stock report: warehouse, product, on hand, reserved,
 * available, updated, actions. The table renders identifiers rather than names,
 * so the two quantities are read positionally.
 */
const ON_HAND_CELL = 2;
const RESERVED_CELL = 3;

const readNumber = async (text: Promise<string>): Promise<number> => {
  const value = Number((await text).replace(/\s/gu, ''));
  if (!Number.isFinite(value)) throw new Error('Кількість у таблиці залишків не є числом');
  return value;
};

/** Reads the CENTRAL row of the stock report for one product. */
const readCentralStock = async (page: Page, productId: string): Promise<StockRow> => {
  await page.goto(`/warehouse/stock?productId=${encodeURIComponent(productId)}`);
  await expect(page.getByRole('heading', { name: 'Залишки' })).toBeVisible({
    timeout: FIRST_LOAD_TIMEOUT,
  });

  const row = page.getByRole('row').filter({ hasText: CENTRAL_WAREHOUSE_CODE });
  await expect(row).toHaveCount(1, { timeout: FIRST_LOAD_TIMEOUT });

  const cells = row.getByRole('cell');
  return {
    onHand: await readNumber(cells.nth(ON_HAND_CELL).innerText()),
    reserved: await readNumber(cells.nth(RESERVED_CELL).innerText()),
  };
};

/** The catalogue list is the only place the identifier of a product surfaces. */
const readProductId = async (page: Page, sku: string): Promise<string> => {
  await page.goto(`/products?search=${encodeURIComponent(sku)}`);
  await expect(page.getByRole('heading', { name: 'Товари' })).toBeVisible({
    timeout: FIRST_LOAD_TIMEOUT,
  });

  const row = page.getByRole('row').filter({ hasText: sku });
  await expect(row).toHaveCount(1, { timeout: FIRST_LOAD_TIMEOUT });
  await row.click();

  await expect(page).toHaveURL(cardUrlPattern('products'));
  return idFromUrl(page.url());
};

/**
 * One chain, not a set of independent checks: every step stands on the record
 * the previous one made. That is what shows the client working against a live
 * API rather than against a fixture.
 */
test('наскрізний сценарій: контакт → угода → замовлення → склад → аудит', async ({ page }) => {
  const contacts = new ContactsPage(page);
  const deals = new DealsPage(page);
  const orders = new OrdersPage(page);
  const audit = new AuditPage(page);

  await test.step('сесія відновлюється зі збереженої cookie', async () => {
    await page.goto('/');
    // The guard shows a spinner until the refresh call answers, so a menu item
    // being visible means the cold start really did rebuild the session.
    await expect(page.getByRole('link', { name: 'Контакти', exact: true })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
    await expect(page).not.toHaveURL(/\/login/u);
  });

  const productId = await test.step('ідентифікатор товару з каталогу', () =>
    readProductId(page, SEED_PRODUCT_SKU));

  const before = await test.step('залишок до підтвердження', () =>
    readCentralStock(page, productId));

  const contactId = await test.step('створення контакту', async () => {
    // The sidebar is on every page of the protected area, so the chain moves on
    // from wherever the previous step left it.
    await contacts.openFromMenu();
    return contacts.create(runData.contact);
  });

  const dealId = await test.step('угода на цьому контакті', async () => {
    await deals.openFromMenu();
    const id = await deals.create({
      title: runData.deal.title,
      amount: runData.deal.amount,
      contactQuery: runData.contact.lastName,
    });
    await expect(page.getByRole('heading', { name: runData.deal.title })).toBeVisible();
    return id;
  });

  await test.step('зміна стадії угоди', async () => {
    await deals.moveToStage('Кваліфіковано');
    await expect(page.getByText('Кваліфіковано', { exact: true }).first()).toBeVisible();
  });

  const orderId = await test.step('замовлення на цю угоду', async () => {
    await orders.openFromMenu();
    return orders.create({
      contactId,
      dealId,
      sku: SEED_PRODUCT_SKU,
      quantity: ORDER_ITEM_QUANTITY,
    });
  });

  await test.step('підтвердження резервує залишок', async () => {
    await orders.changeStatus('Підтверджено');

    const afterConfirm = await readCentralStock(page, productId);
    expect(afterConfirm.reserved).toBe(before.reserved + ORDER_ITEM_QUANTITY);
    // Confirmation only sets the units aside; nothing has left the shelf yet.
    expect(afterConfirm.onHand).toBe(before.onHand);
  });

  await test.step('виконання списує залишок', async () => {
    await page.goto(`/orders/${orderId}`);
    // The machine passes through payment before an order may be fulfilled.
    await orders.changeStatus('Оплачено');
    await orders.changeStatus('Виконано');

    const afterFulfil = await readCentralStock(page, productId);
    expect(afterFulfil.onHand).toBe(before.onHand - ORDER_ITEM_QUANTITY);
    expect(afterFulfil.reserved).toBe(before.reserved);
  });

  await test.step('записи в аудиті', async () => {
    await audit.openForEntity(contactId);
    await expect(audit.entryWithAction('Створено').first()).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });

    await audit.openForEntity(dealId);
    await expect(audit.entryWithAction('Зміна стадії').first()).toBeVisible();

    await audit.openForEntity(orderId);
    await expect(audit.entryWithAction('Зміна статусу').first()).toBeVisible();
  });

  await test.step('вихід', async () => {
    // The application header is the one that carries the theme switch; the page
    // heading of a route is a banner as well.
    const header = page
      .getByRole('banner')
      .filter({ has: page.getByRole('button', { name: 'Перемкнути тему' }) });

    await header.getByRole('button').last().click();
    await page.getByRole('menuitem', { name: 'Вийти', exact: true }).click();

    await expect(page).toHaveURL(/\/login/u);
    await expect(page.getByRole('button', { name: 'Увійти', exact: true })).toBeVisible();
  });
});
