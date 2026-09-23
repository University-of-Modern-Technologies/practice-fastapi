/**
 * Everything one run needs to be distinguishable from every other run. The
 * scenario writes into a live database that is never emptied between runs, so
 * names carry a suffix instead of assuming the tables start out clean.
 */

/** A cold container answers its very first request slowly. */
export const FIRST_LOAD_TIMEOUT = 60_000;

/** Seed catalogue position the order is built from. */
export const SEED_PRODUCT_SKU = 'LIC-TEAM-01';

/** Code of the warehouse a confirmation reserves against. */
export const CENTRAL_WAREHOUSE_CODE = 'CENTRAL';

/** How many units the order takes, and therefore how much stock has to move. */
export const ORDER_ITEM_QUANTITY = 2;

const DEFAULT_EMAIL = 'admin@crm-training.example';

const stamp = (): string => new Date().toISOString().replace(/\D/gu, '').slice(0, 14);

/** Timestamp plus noise: two runs started in the same second still differ. */
const RUN_TAG = `${stamp()}-${Math.random().toString(36).slice(2, 6)}`;

export const runData = {
  tag: RUN_TAG,
  contact: {
    lastName: `Смоук-${RUN_TAG}`,
    firstName: 'Сценарій',
    email: `smoke-${RUN_TAG}@crm-training.example`,
  },
  deal: {
    title: `Смоук-угода ${RUN_TAG}`,
    amount: '12000.00',
  },
} as const;

export interface Credentials {
  readonly email: string;
  readonly password: string;
}

/**
 * Read lazily rather than at import time: listing the tests must work on a
 * machine that has no password at hand.
 */
export const readCredentials = (): Credentials => {
  const email = process.env.E2E_EMAIL ?? DEFAULT_EMAIL;
  const password = process.env.E2E_PASSWORD;

  if (!password) {
    throw new Error(
      [
        'Не задано змінну оточення E2E_PASSWORD.',
        `Сценарій входить як ${email}, а пароль сідованих користувачів у репозиторії не зберігається.`,
        'Візьміть те саме значення, що й SEED_USER_PASSWORD у стеку, проти якого запускаєте тест:',
        '  PowerShell:  $env:E2E_PASSWORD = "<пароль>"',
        '  bash:        export E2E_PASSWORD="<пароль>"',
      ].join('\n'),
    );
  }

  return { email, password };
};

/** `…/contacts/2f0a…` → `2f0a…`. The card route is where an id becomes known. */
export const idFromUrl = (url: string): string => {
  const id = new URL(url).pathname.split('/').filter(Boolean).pop();
  if (id === undefined) throw new Error(`Не вдалося прочитати ідентифікатор з адреси: ${url}`);
  return id;
};

/** Matches a card route of the given section, e.g. `/deals/<uuid>`. */
export const cardUrlPattern = (section: string): RegExp =>
  new RegExp(`/${section}/[0-9a-f-]{36}$`, 'u');
