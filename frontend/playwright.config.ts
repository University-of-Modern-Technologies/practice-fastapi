import { defineConfig, devices } from '@playwright/test';

/**
 * The address the browser opens. Defaults to the port the `web` service of the
 * compose stack publishes, so a locally running stack needs no configuration.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3100';

/**
 * Written once by the setup project and reused by every test. The access token
 * lives in memory only, so what is stored here is the httpOnly refresh cookie —
 * enough for the client to rebuild the session on a cold load.
 */
export const STORAGE_STATE = 'e2e/.auth/user.json';

export default defineConfig({
  testDir: './e2e',
  // The scenario is one chain against one database; parallel copies of it would
  // race over the same stock rows.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  // A cold container answers its first request slowly; the chain itself is long.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  // The HTML report is always written: CI uploads it as an artifact, and a
  // local failure is worth reading afterwards too.
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
    locale: 'uk-UA',
    timezoneId: 'Europe/Kyiv',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'smoke',
      testMatch: /.*\.spec\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], storageState: STORAGE_STATE },
    },
  ],
});
