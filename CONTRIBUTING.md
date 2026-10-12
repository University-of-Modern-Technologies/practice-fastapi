# Як внести зміну

Шлях від форку до першого pull request. Запуск системи й усі команди — у
[`README.md`](README.md), локальна розробка, тести й міграції — у
[`docs/development.md`](docs/development.md), що відбувається після злиття — у
[`docs/deployment.md`](docs/deployment.md).

Коротко: працюєш у **власному форку**, кожна зміна — в окремій гілці від
`master`, перед push проганяєш `uv run poe check`, pull request відкриваєш **у
своєму ж форку** з гілки в `master`. В оригінальному репозиторії є ще гілка
`develop`: між релізами туди зливаються зміни самого репозиторію, а в `master`
вони потрапляють релізом. Для роботи у форку `develop` не потрібна.

## 1. Форк і клон

1. Натисни **Fork** на сторінці репозиторію. Галочку «Copy the `master` branch
   only» лишай: `develop` у форку не знадобиться.
2. Клонуй **свій форк**, а не оригінал:

   ```bash
   git clone https://github.com/<твій-логін>/<назва-репозиторію>.git
   cd <назва-репозиторію>
   uv run poe setup
   ```

3. Якщо ти вже клонував оригінал, перенаправ `origin` на форк, а оригінал
   залиш як `upstream`, щоб забирати з нього оновлення:

   ```bash
   git remote rename origin upstream
   git remote add origin https://github.com/<твій-логін>/<назва-репозиторію>.git
   git remote -v
   ```

   Ознака, що `origin` досі веде не туди: `git push` відповідає відмовою в
   правах (`Permission denied`, `403`).

Оновити свій `master` з оригіналу — кнопкою **Sync fork** на сторінці форку або
командами `git fetch upstream` і `git merge upstream/master` у локальному
`master`.

## 2. Увімкнути GitHub Actions у форку

У щойно створеному форку GitHub Actions **вимкнені**, і перевірки не запустяться
ні для push, ні для pull request. Обходу через налаштування чи API немає —
потрібна одна дія руками:

1. Відкрий вкладку **Actions** свого форку.
2. Натисни **I understand my workflows, go ahead and enable them**.

Зробити це досить один раз. Якщо pull request уже відкритий, перевірки
запустяться з наступним push у його гілку. Запустити їх вручну можна там же,
на вкладці **Actions**: workflow **CI** → **Run workflow**.

Секретів workflow не потребують, тож у форку більше нічого налаштовувати не
треба.

## 3. Гілка на кожну зміну

```bash
git switch master
git pull
git switch -c feat/product-archive
```

- Одна гілка — одна зміна. Сторонні правки, помічені поруч, ідуть в окрему
  гілку або в розділ «Межі» опису pull request.
- Назва гілки — `<тип>/<коротко-про-зміну>` з тими самими типами, що й у
  комітах: `feat/product-archive`, `fix/order-total-rounding`,
  `docs/deployment`.
- Прямо в `master` не комітять: кожна зміна потрапляє туди через pull request.

## 4. Коміти

Повідомлення комітів — у форматі
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/), як в
історії `master`:

```
<тип>(<область>): <що змінилося для системи>
```

| Тип | Коли |
|---|---|
| `feat` | нова можливість |
| `fix` | виправлення дефекту |
| `test` | лише тести |
| `refactor` | зміна будови без зміни поведінки |
| `docs` | лише документація |
| `build`, `ci`, `chore` | збірка, workflow, службове |

Область — модуль або частина системи: `products`, `orders`, `auth`, `web`,
`ci`. Наприклад: `feat(products): add archive and restore actions`.

Кожен коміт лишає систему робочою. Зміна моделей разом із міграцією — окремий
коміт, нова дія — окремий, тести лягають поруч зі зміною, яку перевіряють.
Правки за зауваженнями review — окремими комітами поверх наявних, щоб друге коло
перевірки читало лише їх.

Хук перед комітом, який ставить `setup`, форматує й лінтить файли, що йдуть у
коміт. Якщо він щось виправив, коміт зупиняється: переглянь правки, зроби
`git add` і закоміть ще раз. Тести хук не запускає.

## 5. Перевірити на машині, перш ніж пушити

```bash
uv run poe check
```

`check` проганяє те саме, що завдання **API checks** і **Web client checks** у
CI: формат, лінт, типи й тести бекенда, а для клієнта — формат, лінт, типи,
юніт-тести й збірку. Окремо, якщо зміна їх зачіпає:

| Що змінив | Що ще прогнати |
|---|---|
| сервіс, запити до бази, транзакції | `uv run poe docker:db`, потім `uv run poe test:integration` |
| моделі в `backend/app/db/models/` | у `backend/`: `uv run alembic revision --autogenerate -m "…"`, прочитати згенероване й закомітити міграцію разом із моделями |
| маршрути, схеми запитів чи відповідей, відмови | у `backend/`: `uv run python -m scripts.export_openapi` і закомітити `backend/openapi.json` |
| `Dockerfile`, залежності, `compose.yaml` | `uv run poe docker:build` |

Потім:

```bash
git push -u origin feat/product-archive
```

## 6. Pull request — у своєму форку

1. На сторінці форку натисни **Compare & pull request** (або **Pull requests →
   New pull request**).
2. **Перевір base repository.** GitHub за замовчуванням пропонує влити зміну в
   оригінальний репозиторій. Обери свій форк: **base repository** —
   `<твій-логін>/<назва-репозиторію>`, **base** — `master`, **compare** — твоя
   гілка.
3. Назва pull request — у тій самій формі, що й коміти:
   `feat(products): add archive and restore actions`.
4. Поки опис не дописаний, відкривай pull request як чернетку: стрілка біля
   кнопки створення → **Create draft pull request**.
5. Заповни шаблон, який GitHub підставить сам
   (`.github/pull_request_template.md`):

   | Розділ | Що туди писати |
   |---|---|
   | **Контекст** | яку задачу закриває зміна й чому вона виникла, два-три речення |
   | **Суть зміни** | що змінилося для системи, а не для файлів; переказ дифа не потрібен |
   | **Як перевірити** | сценарій, який інша людина пройде на своїй машині з нуля, або тест, на який варто подивитися |
   | **Межі** | що свідомо лишилося поза зміною і чому, зокрема помічене поруч |

6. Дочекайся зелених перевірок біля pull request і зніми позначку чернетки
   (**Ready for review**).

З терміналу те саме робить `gh`; репозиторій треба назвати явно, інакше `gh`
теж запропонує оригінал:

```bash
gh pr create --draft --repo <твій-логін>/<назва-репозиторію> --base master
```

## 7. Що перевіряє CI

Workflow **CI** (`.github/workflows/ci.yml`) запускається на кожен pull request у
`master` чи `develop`, на кожен новий push у його гілку і на push у `develop`.
Новий push скасовує попередній незакінчений прогін.

| Завдання | Що робить | Як відтворити на машині |
|---|---|---|
| **API checks** | `uv sync --locked`, формат і лінт (ruff), типи (mypy), тести (pytest), зокрема збіг `openapi.json` з кодом | `uv run poe check:api` |
| **Web client checks** | формат, лінт, типи, юніт-тести, production-збірка клієнта | `uv run poe check:web` |
| **Integration tests** | інтеграційні тести на справжніх PostgreSQL, Redis і MongoDB | `uv run poe docker:db`, потім `uv run poe test:integration` |
| **Migrations in sync with the models** | застосовує всі міграції до порожньої бази й порівнює результат із моделями (`alembic check`) | у `backend/` проти `docker:db`: `uv run alembic check` |
| **Production images** | збирає production-образи | `uv run poe docker:build` |
| **ci-success** | зелений, лише якщо зелені всі завдання вище | — |

`uv sync --locked` падає, якщо `backend/uv.lock` не відповідає
`backend/pyproject.toml`: після зміни залежностей закоміть і оновлений
`uv.lock`.

Червона позначка біля pull request — це посилання: **Details** відкриває лог
завдання, у якому видно команду й помилку. Відтвори її відповідною командою з
таблиці, виправ і запуш ще один коміт.

Якщо хочеш, щоб GitHub не давав злити pull request з червоними перевірками,
додай у форку правило для `master` (**Settings → Branches**) з обов'язковою
перевіркою `ci-success`. У форк такі правила не копіюються.

## 8. Після злиття в `master`

Злиття pull request у `master` запускає workflow **Deploy (simulated)**
(`.github/workflows/deploy.yml`): ті самі перевірки, потім збірку
production-образів, запуск усієї системи в тимчасовому середовищі, перевірки
через nginx і прибирання середовища. Результат — у **Summary** прогону, а
успішний прогін позначається релізом `deploy-<коміт>`. Справжнього production
за цим немає. Подробиці — у [`docs/deployment.md`](docs/deployment.md).
