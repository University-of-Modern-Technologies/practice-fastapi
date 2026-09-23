import { expect, test as setup } from '@playwright/test';
import { STORAGE_STATE } from '../playwright.config';
import { FIRST_LOAD_TIMEOUT, readCredentials } from './fixtures/test-data';
import { LoginPage } from './pages/login.page';

/**
 * Signs in once for the whole run. The access token never leaves memory, so the
 * only thing worth storing is the httpOnly refresh cookie the API sets: a cold
 * page load then rebuilds the session with a single `POST /auth/refresh`.
 */
setup('вхід і збереження сесії', async ({ page }) => {
  const { email, password } = readCredentials();

  const login = new LoginPage(page);
  await login.open();
  await login.signIn(email, password);

  // The guard holds the protected area until the session is known, so a visible
  // menu is the proof that the sign-in actually took.
  await expect(page.getByRole('link', { name: 'Контакти', exact: true })).toBeVisible({
    timeout: FIRST_LOAD_TIMEOUT,
  });
  await expect(page).not.toHaveURL(/\/login/u);

  await page.context().storageState({ path: STORAGE_STATE });
});
