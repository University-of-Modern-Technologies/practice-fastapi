# Навчальна CRM API — FastAPI

HTTP API і канал реального часу навчальної CRM на FastAPI, SQLAlchemy,
PostgreSQL, Redis і MongoDB. Контракт описано в OpenAPI (`/api/docs`), і з
ним працює веб-клієнт із теки `frontend`.

## Вимоги

- [uv](https://docs.astral.sh/uv/) 0.11+ — Python 3.13 він поставить сам
- Docker — для PostgreSQL 17, Redis 7 і MongoDB 7

## Запуск

Команди стека запускаються з кореня репозиторію; `uv run poe` без аргументів
показує їх список. Команди самого бекенда — міграції, наповнення, перевірки —
з цієї теки.

**Усе в контейнерах** (з кореня репозиторію):

```bash
uv run poe setup   # обидва .env із новими секретами, перевірка портів
uv run poe start   # стек у Docker, API перезапускається при збереженні файла
```

Застосунок — на http://localhost:8080. Повний перелік команд, адрес і портів —
у README кореня репозиторію.

**Застосунок на машині, сховища в контейнерах:**

```bash
uv run poe setup                 # з кореня репозиторію
uv run poe start:infra           # лише PostgreSQL, Redis і MongoDB
cd backend
uv run alembic upgrade head      # міграції
uv run python -m scripts.seed    # базове наповнення
cd ..
uv run poe dev                   # API на http://localhost:8000
```

Документація — http://localhost:8000/api/docs, схема — `/api/openapi.json`.
Повний стек при цьому зупиняють (`uv run poe stop`): його контейнер `api`
займає той самий порт 8000 і працює з тією самою базою.

## Оточення

Налаштування лежать у двох файлах, і бекенд читає обидва:

| Файл | Що в ньому |
|---|---|
| `.env` у корені репозиторію | спільне для стека й бекенда: `APP_ENV`, порти (`API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `MONGO_PORT`…), `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD`, `MONGO_DB`/`MONGO_USER`/`MONGO_PASSWORD` |
| `backend/.env` | лише бекенда: JWT-секрети, `SEED_USER_PASSWORD`, `SEED_ALLOW_PRODUCTION`, `LOG_LEVEL`, CORS, ліміти, кеш, журнал подій, `WS_PATH`, інтеграції |

Пріоритет — змінна середовища процесу, потім `backend/.env`, потім кореневий
`.env`. Шляхи до файлів рахуються від теки бекенда, тож міграції, наповнення й
тести знаходять їх, хоч би з якої теки їх запущено. Файла може й не бути.

`DATABASE_URL`, `REDIS_URL` і `MONGODB_URL` окремо задавати не треба — вони
збираються з частин:

| Адреса | Із чого | Хост і порт за замовчуванням |
|---|---|---|
| `DATABASE_URL` | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `127.0.0.1:5432` |
| `REDIS_URL` | `REDIS_HOST`, `REDIS_PORT` | `127.0.0.1:6379` |
| `MONGODB_URL` | `MONGO_HOST`, `MONGO_PORT`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_DB` | `127.0.0.1:27017` |

Явно заданий `DATABASE_URL`, `REDIS_URL` чи `MONGODB_URL` завжди перемагає
зібраний. Хост за замовчуванням — саме `127.0.0.1`, а не `localhost`: сховища
слухають лише IPv4, а `localhost` на Windows спершу пробує IPv6 і втрачає на
цьому по дві секунди на кожне з'єднання. У Docker compose задає хости `postgres`,
`redis` і `mongo`.

API слухає порт `PORT`, а без нього — `API_PORT` із кореневого `.env`; типово
8000.

## База даних

У повному стеку міграції й наповнення застосовує сервіс `migrate` перед
стартом API — руками це знадобиться лише для запуску на машині, точкової
перевірки чи повторного прогону:

```bash
uv run alembic upgrade head
uv run python -m scripts.seed
```

Обидві команди читають ті самі два `.env`, що й застосунок, і `DATABASE_URL`
їм не потрібен. Наповнення відмовляється працювати з паролем `change-me`, а в
`production` — без `SEED_ALLOW_PRODUCTION=true`.

### Демонстраційний набір даних

Поверх базового seed можна завантажити великий набір за дванадцять місяців —
сотні контактів і угод, близько тисячі замовлень, рухи товару й аудит:

```bash
uv run poe db:seed:demo           # з кореня репозиторію: у стеку, в контейнері
uv run python -m scripts.demo_seed  # проти бази, до якої ведуть .env
```

Це **окрема команда й окремі дані**. Базовий seed вона не чіпає: видаляє лише
ті рядки, які сама ж і записала минулого разу, тож запускати її можна скільки
завгодно разів. Рядки беруться з `scripts/demo_data/` — готового набору
файлів у репозиторії.

Порядок має значення: `scripts.seed` спершу, `scripts.demo_seed` після — ролі
демонстраційних облікових записів шукаються за назвою, а не створюються.

Щоб побачити SQL міграції без підключення до бази:

```bash
uv run alembic upgrade head --sql
```

Нову міграцію після зміни моделей генерує сам Alembic — проти запущеної бази:

```bash
uv run alembic revision --autogenerate -m "короткий опис зміни"
```

Згенероване завжди варто прочитати: автогенерація ловить зміни колонок і
таблиць, але не бачить намірів — перейменування поля вона запише як
видалення старого й додавання нового.

## Перевірки

```bash
uv run ruff format --check .   # форматування
uv run ruff check .            # статичний аналіз
uv run mypy                    # типи, strict
uv run pytest                  # тести
```

`pytest` збирає всі рівні одразу, але інтеграційні тести пропускаються, поки не
піднято сховища: у підсумку прогону вони видні як `skipped`. Піднятого стека
самого по собі не досить — тести читають адреси сховищ лише зі змінних
середовища процесу, а не з `.env` і не з частин, тому їх треба задати явно в
тому самому терміналі (порти й паролі — з кореневого `.env`):

```powershell
$env:DATABASE_URL = 'postgresql://practice_crm:<POSTGRES_PASSWORD>@127.0.0.1:<POSTGRES_PORT>/practice_crm'
$env:REDIS_URL = 'redis://127.0.0.1:<REDIS_PORT>'
$env:MONGODB_URL = 'mongodb://practice_crm:<MONGO_PASSWORD>@127.0.0.1:<MONGO_PORT>/practice_events?authSource=admin'
uv run pytest
```

## Структура

```
app/
  core/          налаштування, помилки, обробники, серіалізація, безпека
  middleware/    correlation id, логування запитів, заголовки, ліміт тіла, rate limit
  db/            підключення, базовий клас моделей, типи колонок, моделі
  cache/         фасад Redis: get / set / remember / delete / invalidate_prefix
  events/        журнал подій у MongoDB (append-only, TTL-індекс)
  realtime/      WebSocket-шлюз із RBAC на підписках
  observability/ реєстр метрик і /api/metrics під токеном
  health/        проби живучості й готовності
  container.py   композиційний корінь: увесь граф об'єктів
  lifespan.py    підключення/відключення, публікація графа на app.state
  factory.py     create_app(): middleware, обробники помилок, роутери, OpenAPI
  modules/       13 доменних модулів (по одному пакету на домен)
tests/
  unit/          тести без зовнішніх залежностей
  integration/   тести проти справжніх PostgreSQL, Redis і MongoDB
```

Кожен доменний модуль має однаковий набір файлів: `router.py`, `service.py`,
`schemas.py`, `types.py`, за потреби `dependencies.py`.

## Модулі

Усе під префіксом `/api/v1`; 72 операції разом.

| Модуль | Операцій | Про що |
|---|---|---|
| `auth` | 4 | вхід, оновлення токена, вихід, поточний користувач |
| `users` | 7 | користувачі та їхні сесії |
| `rbac` | 4 | ролі, дозволи, перевірка доступу |
| `contacts` | 5 | CRUD контактів із soft delete |
| `deals` | 6 | угоди й машина станів стадій |
| `products` | 5 | каталог товарів |
| `orders` | 10 | замовлення, позиції, переходи статусів, резерв стоку |
| `warehouse` | 12 | склади, залишки, 5 операцій зі стоком, рухи |
| `audit` | 3 | журнал аудиту |
| `settings` | 4 | реєстр налаштувань із типами |
| `analytics` | 6 | агрегатні звіти з кешуванням |
| `integrations` | 4 | доставка: тарифи, відправлення, стан інтеграції |
| `ai` | 2 | стислий переказ угоди, класифікація звернення |

Поза контрактом, але теж під `/api`: `/api/health/{live,ready,startup,info}`,
`/api/docs`, `/api/openapi.json`, `/api/metrics` (лише коли задано
`METRICS_TOKEN`) і WebSocket на `WS_PATH` (типово `/api/v1/realtime`).

## Зовнішні служби

`integrations` і `ai` працюють без жодного налаштування: без `DELIVERY_BASE_URL`
модуль доставки використовує вбудований stub-транспорт, без `AI_ENDPOINT_URL`
асистент відповідає офлайн-моком із шаблонними відповідями. Обидва варіанти
детерміновані, тож свіжий checkout проходить наскрізний сценарій без жодного
зовнішнього акаунта. Решта змінних (таймаути, пороги circuit breaker'а, ліміти
токенів) — у `backend/.env.example`.

Клієнт доставки й провайдер асистента створюються один раз на процес у
`app/container.py` і публікуються на `app.state`: стан circuit breaker'а мусить
жити довше за один запит, інакше він не breaker.

## Порти

Порти змінюються в кореневому `.env`. API займає 8000 і в контейнері, і на
машині, тож одночасно працює щось одне з двох.

| Порт | Змінна | Сервіс |
|---|---|---|
| 8080 | `HTTP_PORT` | застосунок через nginx |
| 8000 | `API_PORT` | API — у контейнері чи на машині (`uv run poe dev`) |
| 3000 | `WEB_PORT` | веб-клієнт |
| 5432 | `POSTGRES_PORT` | PostgreSQL |
| 6379 | `REDIS_PORT` | Redis |
| 27017 | `MONGO_PORT` | MongoDB |
