"""Fixtures for the scenarios that need real storage.

Every fixture here is allowed to *skip*, never to fail. A developer without
Docker running must be able to type `pytest` and get a green run with a handful
of skips; a red one would train the team to ignore red.

The connection strings come from the environment — `DATABASE_URL`, `REDIS_URL`
and `MONGODB_URL`, the same three the application reads. The local compose stack
publishes them on the shifted ports (5433 / 6380 / 27018) so that two backends
can run side by side, which is why nothing here hard-codes a port.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import hash_password
from app.core.settings import Settings
from app.db.enums import PermissionScope
from app.db.models.contact import Contact
from app.db.models.product import Product
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.user import User
from app.db.models.warehouse import Warehouse

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Placeholders for the settings the migration subprocess validates but never
#: uses. They are syntactically valid and point nowhere.
_UNUSED_SETTINGS = {
    "APP_ENV": "test",
    "JWT_ACCESS_SECRET": "integration-secret-value-that-is-long-enough",
    "JWT_REFRESH_SECRET": "integration-secret-value-that-is-long-enough",
    "REDIS_URL": "redis://localhost:6379",
    "MONGODB_URL": "mongodb://localhost:27017/practice_events",
}

CONNECT_TIMEOUT_SECONDS = 3.0


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Marks everything in this package, so `-m "not integration"` works."""
    marker = pytest.mark.integration
    package = Path(__file__).parent
    for item in items:
        if package in Path(str(item.fspath)).parents:
            item.add_marker(marker)


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def asyncpg_url(url: str) -> str:
    """Normalises a URL the way the application normalises it."""
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=url,
        jwt_access_secret=_UNUSED_SETTINGS["JWT_ACCESS_SECRET"],
        jwt_refresh_secret=_UNUSED_SETTINGS["JWT_REFRESH_SECRET"],
        redis_url=_UNUSED_SETTINGS["REDIS_URL"],
        mongodb_url=_UNUSED_SETTINGS["MONGODB_URL"],
    ).database_url


async def _run_sql(url: str, statements: list[str]) -> None:
    """Runs statements outside a transaction — `CREATE DATABASE` needs that."""
    engine = create_async_engine(asyncpg_url(url), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def _reachable(url: str) -> str | None:
    """Returns the reason the server is unusable, or `None` when it answers."""
    engine = create_async_engine(asyncpg_url(url), poolclass=NullPool)
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.exec_driver_sql("SELECT 1")
    except Exception as error:
        return repr(error)
    else:
        return None
    finally:
        await engine.dispose()


def run_alembic(command: str, revision: str, *, database_url: str) -> None:
    """Drives the real Alembic entry point against the given database.

    A subprocess rather than the Python API on purpose: the migration
    environment reads the settings singleton at import time and drives its own
    event loop, and both of those belong to a process of their own.
    """
    environment = {**os.environ, **_UNUSED_SETTINGS, "DATABASE_URL": database_url}
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
    """The maintenance URL every scratch database is created from."""
    url = _env("DATABASE_URL")
    if url is None:
        pytest.skip("DATABASE_URL is not set; start the compose stack to run these")
    reason = asyncio.run(_reachable(url))
    if reason is not None:
        pytest.skip(f"PostgreSQL is not reachable at DATABASE_URL: {reason}")
    return url


@pytest.fixture
def scratch_database(postgres_url: str) -> Iterator[str]:
    """An empty database of its own, dropped when the test is done.

    Function-scoped because the tests that ask for it are the ones that create
    and destroy the whole schema; sharing one would make them order-dependent.
    """
    name = f"practice_it_{uuid.uuid4().hex[:10]}"
    asyncio.run(_run_sql(postgres_url, [f'CREATE DATABASE "{name}"']))
    try:
        yield _with_database(postgres_url, name)
    finally:
        asyncio.run(
            _run_sql(
                postgres_url,
                [
                    # A leftover connection would make the drop hang.
                    f"""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                        WHERE datname = '{name}' AND pid <> pg_backend_pid()""",
                    f'DROP DATABASE IF EXISTS "{name}"',
                ],
            )
        )


@pytest.fixture(scope="session")
def migrated_database(postgres_url: str) -> Iterator[str]:
    """One migrated database shared by every scenario that only reads and writes rows."""
    name = f"practice_it_{uuid.uuid4().hex[:10]}"
    url = _with_database(postgres_url, name)
    asyncio.run(_run_sql(postgres_url, [f'CREATE DATABASE "{name}"']))
    try:
        run_alembic("upgrade", "head", database_url=url)
        yield url
    finally:
        asyncio.run(
            _run_sql(
                postgres_url,
                [
                    f"""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                        WHERE datname = '{name}' AND pid <> pg_backend_pid()""",
                    f'DROP DATABASE IF EXISTS "{name}"',
                ],
            )
        )


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


@pytest.fixture
def integration_settings(migrated_database: str) -> Settings:
    """Settings pointing at whichever services the environment published."""
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated_database,
        jwt_access_secret=_UNUSED_SETTINGS["JWT_ACCESS_SECRET"],
        jwt_refresh_secret=_UNUSED_SETTINGS["JWT_REFRESH_SECRET"],
        redis_url=_env("REDIS_URL") or _UNUSED_SETTINGS["REDIS_URL"],
        mongodb_url=_env("MONGODB_URL") or _UNUSED_SETTINGS["MONGODB_URL"],
        redis_key_prefix=f"it-{uuid.uuid4().hex[:8]}:",
    )


@pytest.fixture
def store_settings() -> Settings:
    """Settings for the two stores that need no database behind them.

    Separate from `integration_settings` on purpose: a machine with Redis and
    MongoDB but no PostgreSQL should still be able to run these scenarios.
    """
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://unused:unused@localhost:5432/unused",
        jwt_access_secret=_UNUSED_SETTINGS["JWT_ACCESS_SECRET"],
        jwt_refresh_secret=_UNUSED_SETTINGS["JWT_REFRESH_SECRET"],
        redis_url=_env("REDIS_URL") or _UNUSED_SETTINGS["REDIS_URL"],
        mongodb_url=_env("MONGODB_URL") or _UNUSED_SETTINGS["MONGODB_URL"],
        # A namespace of its own, so a run never disturbs a developer's data
        # and two runs never disturb each other.
        redis_key_prefix=f"it-{uuid.uuid4().hex[:8]}:",
    )


@pytest.fixture(scope="session")
def redis_url() -> str:
    url = _env("REDIS_URL")
    if url is None:
        pytest.skip("REDIS_URL is not set; start the compose stack to run these")
    return url


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    url = _env("MONGODB_URL")
    if url is None:
        pytest.skip("MONGODB_URL is not set; start the compose stack to run these")
    return url


def skip_unless_available(error: Exception, service: str) -> Any:
    """Turns an unreachable service into a skip with the reason attached."""
    return pytest.skip(f"{service} is not usable: {error!r}")


# ---------------------------------------------------------------------------
# Row builders
#
# Every scenario needs a handful of rows before it can say anything, and every
# one of them needs different rows. These build the minimum a foreign key
# demands and leave the rest to the caller.
# ---------------------------------------------------------------------------

SEED_PASSWORD = "integration-password"


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
