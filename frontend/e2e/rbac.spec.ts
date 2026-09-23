import { expect, test, type Page } from '@playwright/test';
import { FIRST_LOAD_TIMEOUT } from './fixtures/test-data';
import { LoginPage } from './pages/login.page';

/**
 * The read-only account. The seeded roles all share one password, so the same
 * variable the rest of the suite uses opens this one too; a separate variable
 * is honoured for a stack where the accounts were set up by hand.
 */
const VIEWER_EMAIL = process.env.E2E_VIEWER_EMAIL ?? 'viewer@crm-training.example';
const VIEWER_PASSWORD = process.env.E2E_VIEWER_PASSWORD ?? process.env.E2E_PASSWORD;

/**
 * Sections the read-only role holds a `read` grant for, and therefore sees.
 * The dashboard carries no permission at all — it asks for nothing that a
 * signed-in user may not have.
 */
const ALLOWED_MENU = ['Контакти', 'Угоди', 'Замовлення', 'Товари', 'Склад', 'Рухи товару'];

/** Sections the role has no grant for. The menu must not offer them. */
const FORBIDDEN_MENU = [
  'Аналітика',
  'Користувачі',
  'Доступи',
  'Налаштування',
  'Аудит',
  'Інтеграції',
  'AI-помічник',
];

/**
 * Routes reachable only by typing them in. Each must answer with the notice.
 * The role holds no grant on `audit`, `users`, `settings` or `analytics`, and
 * `/roles` is guarded by `users:read` rather than by a permission of its own.
 */
const FORBIDDEN_ROUTES = ['/audit', '/users', '/roles', '/settings', '/analytics'];

/**
 * Routes the role may open, with the heading that proves each one rendered.
 * The grant on `warehouse` is a read of every record, so the whole section is
 * legitimately reachable — refusing here would be the defect.
 */
const ALLOWED_ROUTES: ReadonlyArray<readonly [route: string, heading: string]> = [
  ['/warehouse', 'Склади'],
  ['/warehouse/stock', 'Залишки'],
  ['/warehouse/movements', 'Журнал рухів'],
];

/** The text `PermissionGate` shows in place of a section. */
const REFUSAL = 'Недостатньо прав';

/**
 * The whole sidebar. Menu labels repeat in the dashboard tiles, so a check on
 * an item being present has to say which of the two it means.
 */
const sidebar = (page: Page) => page.getByRole('complementary');

/**
 * The suite signs in itself instead of reusing the stored session: that session
 * belongs to the administrator, and the point here is a different role.
 */
test.use({ storageState: { cookies: [], origins: [] } });

test.describe('обмеження ролі viewer', () => {
  test.skip(
    !VIEWER_PASSWORD,
    'Не задано E2E_VIEWER_PASSWORD (або E2E_PASSWORD). Сценарій входить як ' +
      `${VIEWER_EMAIL}, а паролі сідованих користувачів у репозиторії не зберігаються.`,
  );

  test.beforeEach(async ({ page }) => {
    const login = new LoginPage(page);
    await login.open();
    await login.signIn(VIEWER_EMAIL, VIEWER_PASSWORD ?? '');

    // The guard holds the protected area until the session is known, so a
    // visible menu item is the proof that the sign-in took.
    await expect(sidebar(page).getByRole('link', { name: 'Контакти', exact: true })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
    await expect(page).not.toHaveURL(/\/login/u);
  });

  test('меню показує лише розділи, дозволені ролі', async ({ page }) => {
    for (const label of ALLOWED_MENU) {
      await expect(sidebar(page).getByRole('link', { name: label, exact: true })).toBeVisible();
    }

    for (const label of FORBIDDEN_MENU) {
      await expect(sidebar(page).getByRole('link', { name: label, exact: true })).toHaveCount(0);
    }
  });

  test('прямий перехід у заборонений розділ дає відмову, а не запити', async ({ page }) => {
    for (const route of FORBIDDEN_ROUTES) {
      await test.step(route, async () => {
        await page.goto(route);
        await expect(page.getByText(REFUSAL)).toBeVisible({ timeout: FIRST_LOAD_TIMEOUT });
        // The route stays where it is: refusal is a screen, not a redirect.
        await expect(page).toHaveURL(new RegExp(`${route}$`, 'u'));
      });
    }
  });

  test('дозволений розділ відкривається за прямим посиланням', async ({ page }) => {
    for (const [route, heading] of ALLOWED_ROUTES) {
      await test.step(route, async () => {
        await page.goto(route);
        await expect(page.getByRole('heading', { name: heading })).toBeVisible({
          timeout: FIRST_LOAD_TIMEOUT,
        });
        await expect(page.getByText(REFUSAL)).toHaveCount(0);
      });
    }
  });

  test('у доступному списку немає кнопок створення', async ({ page }) => {
    await page.goto('/products');
    await expect(page.getByRole('heading', { name: 'Товари' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
    // `products:read` without `products:write`: the catalogue opens, the button
    // that would write into it does not exist.
    await expect(page.getByRole('button', { name: 'Додати товар' })).toHaveCount(0);

    await page.goto('/contacts');
    await expect(page.getByRole('heading', { name: 'Контакти' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
    await expect(page.getByRole('button', { name: 'Новий контакт' })).toHaveCount(0);

    await page.goto('/warehouse');
    await expect(page.getByRole('heading', { name: 'Склади' })).toBeVisible({
      timeout: FIRST_LOAD_TIMEOUT,
    });
    // `warehouse:read` reaches every warehouse, `warehouse:write` reaches none.
    await expect(page.getByRole('button', { name: 'Новий склад' })).toHaveCount(0);
  });
});
