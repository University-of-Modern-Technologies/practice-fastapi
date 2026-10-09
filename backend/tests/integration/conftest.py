"""Fixtures for the scenarios that need real storage.

These scenarios are a run of their own: `uv run pytest -m integration`, against
the storage `uv run poe start:infra` brings up from the repository root. A plain
`uv run pytest` deselects them and never touches a server. The tests do not
start Docker themselves.

Inside that explicit run nothing is skipped. A storage that does not answer
stops the whole run before the first test, with its name, its address and the
command that starts it — a green run that quietly tested nothing would be worse
than a red one.

There is no separate test `.env`. The addresses are derived from the same three
layers the application reads — the process, `backend/.env`, the repository's
`.env` — and from the same parts: the same host, port, user and password, with
`_test` appended to the PostgreSQL and MongoDB database names, and Redis on the
same server under a key prefix of its own. A full address in
`DATABASE_URL_TEST`, `REDIS_URL_TEST` or `MONGODB_URL_TEST` wins, which is how
CI points the run at its service containers. The working `DATABASE_URL` is never
read here, and a database whose name does not say it is a test one is refused.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote, urlsplit, urlunsplit

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import MongoClient
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import hash_password
from app.core.settings import ENV_FILES, Settings
from app.db.base import Base
from app.db.enums import OrderStatus, PermissionScope
from app.db.models.contact import Contact
from app.db.models.order import Order
from app.db.models.product import Product
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.user import User
from app.db.models.warehouse import Warehouse
from app.events.model import DEFAULT_EVENT_DATABASE
from app.modules.orders.schemas import CreateOrderRequest, OrderItemRequest, TransitionOrderRequest
from app.modules.orders.service import OrdersService
from app.modules.orders.types import OrderAccess

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The fixed part of the test environment. None of it guards anything real.
TEST_ENVIRONMENT: Final[dict[str, str]] = {
    "APP_ENV": "test",
    "JWT_ACCESS_SECRET": "integration-access-secret-at-least-32-characters",
    "JWT_REFRESH_SECRET": "integration-refresh-secret-at-least-32-characters",
    "SEED_USER_PASSWORD": "LocalTrainingOnly!2026",
    "REDIS_KEY_PREFIX": "crm-test:",
}

#: Syntactically valid addresses for the settings a scenario validates but
#: never uses. They point nowhere, and their names would pass the guard below.
_UNUSED_URLS: Final[dict[str, str]] = {
    "database_url": "postgresql://unused:unused@127.0.0.1:5432/unused_test",
    "redis_url": "redis://127.0.0.1:6379",
    "mongodb_url": "mongodb://127.0.0.1:27017/unused_test",
}

#: A database name has to say it is a test one: `crm_test`, `test-crm`,
#: `crm_testing`. `contest` or `latest` do not count.
_TEST_DATABASE_NAME = re.compile(r"(^|[-_])(test|testing)([-_]|$)", re.IGNORECASE)

#: Where `CREATE DATABASE` is issued from — every PostgreSQL server has it.
MAINTENANCE_DATABASE = "postgres"

START_HINT = "Start the storage from the repository root: uv run poe start:infra"
SEPARATE_RUN_HINT = (
    "start the storage from the repository root with `uv run poe start:infra`, "
    "then run `uv run pytest -m integration` in backend/"
)

CONNECT_TIMEOUT_SECONDS = 3.0

_deselected_key = pytest.StashKey[int]()


# ---------------------------------------------------------------------------
# Selection: this package is a run of its own
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Marks everything in this package, so `-m "not integration"` works."""
    marker = pytest.mark.integration
    package = Path(__file__).parent
    for item in items:
        if package in Path(str(item.fspath)).parents:
            item.add_marker(marker)


def pytest_deselected(items: list[pytest.Item]) -> None:
    """Counts the scenarios the default `-m "not integration"` left out."""
    for item in items:
        if item.get_closest_marker("integration") is not None:
            stash = item.config.stash
            stash[_deselected_key] = stash.get(_deselected_key, 0) + 1


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Says where the deselected scenarios went, so nobody thinks they passed."""
    count = config.stash.get(_deselected_key, 0)
    if count:
        terminalreporter.write_sep("-", "integration tests")
        terminalreporter.write_line(
            f"{count} integration tests are a separate run: {SEPARATE_RUN_HINT}."
        )


# ---------------------------------------------------------------------------
# Test addresses, derived from the application's own env layers
# ---------------------------------------------------------------------------


class StorageConfigError(Exception):
    """A test address that cannot be built, or one that must not be used."""


class _TestAddressSources(BaseSettings):
    """The values a test address is derived from, read like the application's.

    Only the explicit test URLs and the two database names are read here; the
    host, port, user and password are left to `Settings` itself, so a test
    address is assembled by exactly the code that assembles a working one.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url_test: str | None = None
    redis_url_test: str | None = None
    mongodb_url_test: str | None = None
    postgres_db: str | None = None
    mongo_db: str | None = None


def _text(value: str | None) -> str | None:
    """A blank value counts as absent, as it does for the application."""
    if value is None:
        return None
    return value.strip() or None


def _test_name(name: str | None) -> str | None:
    return None if name is None else f"{name}_test"


def _fixed_settings() -> dict[str, Any]:
    return {
        "app_env": TEST_ENVIRONMENT["APP_ENV"],
        "jwt_access_secret": TEST_ENVIRONMENT["JWT_ACCESS_SECRET"],
        "jwt_refresh_secret": TEST_ENVIRONMENT["JWT_REFRESH_SECRET"],
    }


def _assemble(
    field: str, explicit: str | None, parts: dict[str, Any], storage: str, needs: str
) -> str:
    """One storage URL, built by `Settings` from the layered env.

    The field is passed even when it is `None`: an argument outranks every
    env layer, so the working URL from `.env` or the process can never fill
    it, and `None` makes `Settings` assemble the address from its parts. The
    other two URLs are placeholders, so one storage's missing parts never stop
    another storage's scenarios.
    """
    overrides: dict[str, Any] = {**_UNUSED_URLS, field: explicit, **parts}
    try:
        settings = Settings(**_fixed_settings(), **overrides)
    except ValidationError as error:
        # Only the location and the reason: the rendered error repeats the
        # input, and the input holds the passwords.
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        )
        message = f"{storage}: the test address cannot be derived ({reasons}); {needs}"
        raise StorageConfigError(message) from error
    url: str = getattr(settings, field)
    return url


def _database_name(url: str) -> str:
    return unquote(urlsplit(url).path.lstrip("/"))


def _address(url: str) -> str:
    """Where a URL points, without its credentials."""
    parts = urlsplit(url)
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.hostname}{port}{parts.path}"


def postgres_test_url() -> str:
    """The test database: `${POSTGRES_DB}_test`, or `DATABASE_URL_TEST`."""
    sources = _TestAddressSources()
    explicit = _text(sources.database_url_test)
    database = _test_name(_text(sources.postgres_db))
    parts = {} if explicit is not None or database is None else {"postgres_db": database}
    url = _assemble(
        "database_url",
        explicit,
        parts,
        "PostgreSQL",
        "set POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB in the repository root .env, "
        "or DATABASE_URL_TEST",
    )
    name = _database_name(url)
    if not _TEST_DATABASE_NAME.search(name):
        message = (
            f'Refusing to run database tests against "{name}": '
            "the database name must contain a separate test or testing token."
        )
        raise StorageConfigError(message)
    return url


def redis_test_url() -> str:
    """The same Redis server, or `REDIS_URL_TEST`; keys go under `crm-test:`."""
    sources = _TestAddressSources()
    return _assemble(
        "redis_url",
        _text(sources.redis_url_test),
        {},
        "Redis",
        "check REDIS_HOST and REDIS_PORT, or set REDIS_URL_TEST",
    )


def mongodb_test_url() -> str:
    """The test event log: `${MONGO_DB}_test`, or `MONGODB_URL_TEST`."""
    sources = _TestAddressSources()
    explicit = _text(sources.mongodb_url_test)
    database = _test_name(_text(sources.mongo_db))
    parts = {} if explicit is not None or database is None else {"mongo_db": database}
    url = _assemble(
        "mongodb_url",
        explicit,
        parts,
        "MongoDB",
        "set MONGO_DB (and MONGO_USER, MONGO_PASSWORD) in the repository root .env, "
        "or MONGODB_URL_TEST",
    )
    # An address without a database falls back to the application's default,
    # which is the working event log — so that is the name the guard checks.
    name = _database_name(url) or DEFAULT_EVENT_DATABASE
    if not _TEST_DATABASE_NAME.search(name):
        message = (
            f'Refusing to run event store tests against "{name}": '
            "the database name must contain a separate test or testing token."
        )
        raise StorageConfigError(message)
    return url


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def scenario_settings(**overrides: Any) -> Settings:
    """Test settings built from what is passed, with no `.env` file behind them.

    Whatever is not passed is either fixed here or a placeholder, so a scenario
    states every address it actually uses.
    """
    values: dict[str, Any] = {**_fixed_settings(), **_UNUSED_URLS, **overrides}
    return Settings(_env_file=None, **values)


def asyncpg_url(url: str) -> str:
    """Normalises a URL the way the application normalises it."""
    return scenario_settings(database_url=url).database_url


# ---------------------------------------------------------------------------
# Preflight: the run stops before the first test when a storage is missing
# ---------------------------------------------------------------------------


#: Drivers explain a refused connection at length — MongoDB lists its whole
#: topology. The first stretch says what happened; the rest is noise here.
_REASON_LIMIT = 160


def _reason(error: BaseException) -> str:
    """One readable line about why a storage did not answer."""
    detail = " ".join(str(error).split()) or f"no answer within {CONNECT_TIMEOUT_SECONDS:g} s"
    if len(detail) > _REASON_LIMIT:
        detail = detail[: _REASON_LIMIT - 3].rstrip() + "..."
    return f"{type(error).__name__}: {detail}"


async def _postgres_problem(url: str) -> str | None:
    """Returns the reason the server is unusable, or `None` when it answers."""
    engine = create_async_engine(asyncpg_url(url), poolclass=NullPool)
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.exec_driver_sql("SELECT 1")
    except Exception as error:
        return _reason(error)
    else:
        return None
    finally:
        await engine.dispose()


def _check_postgres() -> str | None:
    # The maintenance database, not the test one: the run creates that itself.
    url = _with_database(postgres_test_url(), MAINTENANCE_DATABASE)
    reason = asyncio.run(_postgres_problem(url))
    if reason is None:
        return None
    return f"PostgreSQL is not reachable at {_address(url)}: {reason}"


def _check_redis() -> str | None:
    url = redis_test_url()
    client = Redis.from_url(
        url,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=CONNECT_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    except Exception as error:
        return f"Redis is not reachable at {_address(url)}: {_reason(error)}"
    finally:
        client.close()
    return None


def _check_mongodb() -> str | None:
    url = mongodb_test_url()
    timeout_ms = int(CONNECT_TIMEOUT_SECONDS * 1000)
    client: MongoClient[dict[str, Any]] = MongoClient(
        url, serverSelectionTimeoutMS=timeout_ms, connectTimeoutMS=timeout_ms
    )
    try:
        client.admin.command("ping")
    except Exception as error:
        return f"MongoDB is not reachable at {_address(url)}: {_reason(error)}"
    finally:
        client.close()
    return None


#: The fixture a scenario reaches a storage through, and how that storage is
#: checked. Every scenario that needs PostgreSQL depends on `postgres_url`,
#: directly or through `migrated_database`, so the closure says it all.
_PREFLIGHT: Final[dict[str, Callable[[], str | None]]] = {
    "postgres_url": _check_postgres,
    "redis_url": _check_redis,
    "mongodb_url": _check_mongodb,
}


def pytest_collection_finish(session: pytest.Session) -> None:
    """Checks the storage the selected scenarios need, once, before any runs."""
    if session.config.option.collectonly:
        return

    needed = {
        fixture
        for item in session.items
        if item.get_closest_marker("integration") is not None
        for fixture in getattr(item, "fixturenames", ())
        if fixture in _PREFLIGHT
    }
    problems: list[str] = []
    unreachable = False
    for fixture, check in _PREFLIGHT.items():
        if fixture not in needed:
            continue
        try:
            problem = check()
        except StorageConfigError as error:
            problems.append(str(error))
        else:
            if problem is not None:
                problems.append(problem)
                unreachable = True

    if not problems:
        return
    lines = ["The integration run cannot start:", *(f"  - {problem}" for problem in problems)]
    if unreachable:
        lines.append(START_HINT)
    report = "\n".join(lines)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        pytest.exit(report, returncode=pytest.ExitCode.TESTS_FAILED)
    reporter.write_line("")
    reporter.write_line(report, red=True, bold=True)
    # The details are on screen already; the closing banner only names the cause.
    pytest.exit("integration storage is not available", returncode=pytest.ExitCode.TESTS_FAILED)


def _resolved(resolve: Callable[[], str]) -> str:
    """A test address inside a fixture; a problem fails the test, never skips it."""
    try:
        return resolve()
    except StorageConfigError as error:
        pytest.fail(str(error), pytrace=False)


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


async def _run_sql(url: str, statements: list[str]) -> None:
    """Runs statements outside a transaction — `CREATE DATABASE` needs that."""
    engine = create_async_engine(asyncpg_url(url), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def _database_exists(maintenance_url: str, name: str) -> bool:
    engine = create_async_engine(asyncpg_url(maintenance_url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            found = await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            return found.first() is not None
    finally:
        await engine.dispose()


def _drop_statements(name: str) -> list[str]:
    return [
        # A leftover connection would make the drop hang.
        f"""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = '{name}' AND pid <> pg_backend_pid()""",
        f'DROP DATABASE IF EXISTS "{name}"',
    ]


def run_alembic(command: str, revision: str, *, database_url: str) -> None:
    """Drives the real Alembic entry point against the given database.

    A subprocess rather than the Python API on purpose: the migration
    environment reads the settings singleton at import time and drives its own
    event loop, and both of those belong to a process of their own. The child
    reads the same env layers; what is set here outranks them.
    """
    environment = {
        **os.environ,
        **TEST_ENVIRONMENT,
        "DATABASE_URL": database_url,
        # Validated by the settings, never used by a migration.
        "REDIS_URL": _UNUSED_URLS["redis_url"],
        "MONGODB_URL": _UNUSED_URLS["mongodb_url"],
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = f"alembic {command} {revision} failed:\n{result.stdout}\n{result.stderr}"
        raise AssertionError(message)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """The maintenance URL: the test server's own `postgres` database."""
    return _with_database(_resolved(postgres_test_url), MAINTENANCE_DATABASE)


@pytest.fixture
def scratch_database(postgres_url: str) -> Iterator[str]:
    """An empty database of its own, dropped when the test is done.

    Function-scoped because the tests that ask for it are the ones that create
    and destroy the whole schema; sharing one would make them order-dependent.
    The name extends the test database's, so it passes the same guard.
    """
    base = _database_name(_resolved(postgres_test_url))
    name = f"{base}_{uuid.uuid4().hex[:10]}"
    asyncio.run(_run_sql(postgres_url, [f'CREATE DATABASE "{name}"']))
    try:
        yield _with_database(postgres_url, name)
    finally:
        asyncio.run(_run_sql(postgres_url, _drop_statements(name)))


@pytest.fixture(scope="session")
def migrated_database(postgres_url: str) -> str:
    """The test database, shared by every scenario that only reads and writes rows.

    Created when the server does not have it yet, brought to the latest
    migration, and emptied, so a second run starts from exactly where the
    first one did. Nothing is dropped at the end: the next run reuses it.
    """
    url = _resolved(postgres_test_url)
    name = _database_name(url)
    if not asyncio.run(_database_exists(postgres_url, name)):
        asyncio.run(_run_sql(postgres_url, [f'CREATE DATABASE "{name}"']))
    run_alembic("upgrade", "head", database_url=url)
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    asyncio.run(_run_sql(url, [f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"]))
    return url


@pytest.fixture(scope="session")
def engine(migrated_database: str) -> Iterator[AsyncEngine]:
    """A pool-less engine, so a connection is never reused across event loops."""
    created = create_async_engine(asyncpg_url(migrated_database), poolclass=NullPool)
    try:
        yield created
    finally:
        asyncio.run(created.dispose())


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose every write is undone when the test ends.

    The session joins an outer transaction as a savepoint, so a test may commit
    and roll back exactly as production code does, and the database is still
    left exactly as it was found.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


def _scenario_key_prefix() -> str:
    """The test prefix, with a namespace per scenario under it.

    A developer's data lives under another prefix, and the namespace keeps two
    runs — or two scenarios — from disturbing each other.
    """
    return f"{TEST_ENVIRONMENT['REDIS_KEY_PREFIX']}{uuid.uuid4().hex[:8]}:"


@pytest.fixture
def integration_settings(migrated_database: str, redis_url: str, mongodb_url: str) -> Settings:
    """Settings pointing at the three test stores."""
    return scenario_settings(
        database_url=migrated_database,
        redis_url=redis_url,
        mongodb_url=mongodb_url,
        redis_key_prefix=_scenario_key_prefix(),
    )


@pytest.fixture
def store_settings() -> Settings:
    """Settings for the two stores that need no database behind them.

    Separate from `integration_settings` on purpose: a machine with Redis and
    MongoDB but no PostgreSQL should still be able to run these scenarios. The
    addresses are placeholders; a scenario takes the real one from `redis_url`
    or `mongodb_url`, so it waits only for the storage it actually uses.
    """
    return scenario_settings(redis_key_prefix=_scenario_key_prefix())


@pytest.fixture(scope="session")
def redis_url() -> str:
    """The test Redis: the working server, under the `crm-test:` key prefix."""
    return _resolved(redis_test_url)


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    """The test event log: `${MONGO_DB}_test` on the working server."""
    return _resolved(mongodb_test_url)


# ---------------------------------------------------------------------------
# Row builders
#
# Every scenario needs a handful of rows before it can say anything, and every
# one of them needs different rows. These build the minimum a foreign key
# demands and leave the rest to the caller.
# ---------------------------------------------------------------------------

SEED_PASSWORD = TEST_ENVIRONMENT["SEED_USER_PASSWORD"]


async def create_user(
    session: AsyncSession,
    *,
    name: str = "Test User",
    password: str = SEED_PASSWORD,
    is_active: bool = True,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:12]}@example.com",
        password_hash=hash_password(password),
        name=name,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def grant(
    session: AsyncSession,
    user: User,
    permission_key: str,
    scope: PermissionScope,
    *,
    role_name: str | None = None,
) -> Role:
    """Gives one user one permission at one breadth, through a fresh role."""
    role = Role(id=uuid.uuid4(), name=role_name or f"role-{uuid.uuid4().hex[:8]}")
    permission = await session.scalar(select(Permission).where(Permission.key == permission_key))
    if permission is None:
        permission = Permission(id=uuid.uuid4(), key=permission_key)
        session.add(permission)
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id, scope=scope))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()
    return role


async def create_warehouse(session: AsyncSession, *, is_active: bool = True) -> Warehouse:
    warehouse = Warehouse(
        id=uuid.uuid4(),
        code=f"WH{uuid.uuid4().hex[:8].upper()}",
        name="Integration warehouse",
        is_active=is_active,
    )
    session.add(warehouse)
    await session.flush()
    return warehouse


async def create_product(session: AsyncSession, *, unit_price: str = "19.99") -> Product:
    product = Product(
        id=uuid.uuid4(),
        sku=f"SKU-{uuid.uuid4().hex[:10].upper()}",
        name="Integration product",
        unit_price=Decimal(unit_price),
        currency="USD",
    )
    session.add(product)
    await session.flush()
    return product


async def create_contact(session: AsyncSession, owner: User) -> Contact:
    contact = Contact(
        id=uuid.uuid4(),
        owner_id=owner.id,
        first_name="Ada",
        last_name=f"Byron-{uuid.uuid4().hex[:6]}",
        email=f"contact-{uuid.uuid4().hex[:12]}@example.com",
    )
    session.add(contact)
    await session.flush()
    return contact


#: The one non-branching path forward; CANCELLED is reachable from any of
#: these but is never where an archiving scenario needs to land, so this
#: factory does not offer it.
_FORWARD_PATH = (
    OrderStatus.DRAFT,
    OrderStatus.CONFIRMED,
    OrderStatus.PAID,
    OrderStatus.FULFILLED,
)


async def create_order(
    session: AsyncSession,
    owner: User,
    product: Product,
    *,
    quantity: int = 1,
    status: OrderStatus = OrderStatus.DRAFT,
) -> Order:
    """A DRAFT order for one product, walked forward to `status`.

    Built through `OrdersService` with no stock port, the same shape a unit
    test uses: the transitions move the order's own status without touching
    a warehouse. Good for scenarios that only care what state an order is
    in — a product-archiving check asking "does this product sit in an open
    order" does not need a real reservation to answer that.
    """
    access = OrderAccess(actor_id=owner.id, scope=PermissionScope.ALL)
    service = OrdersService(session)
    created = await service.create(
        access,
        CreateOrderRequest(
            owner_id=owner.id,
            items=[OrderItemRequest(product_id=product.id, quantity=quantity)],
        ),
    )

    target_index = _FORWARD_PATH.index(status)
    version = created.version
    for next_status in _FORWARD_PATH[1 : target_index + 1]:
        moved = await service.transition(
            access, created.id, TransitionOrderRequest(version=version, status=next_status)
        )
        version = moved.version

    order = await session.get(Order, created.id)
    assert order is not None
    return order
