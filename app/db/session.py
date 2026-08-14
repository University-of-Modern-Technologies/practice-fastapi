"""Database connectivity.

One engine per process, one session per request. The session is opened by a
dependency and closed by it, and the request's transaction is committed only if
the handler returned without raising — so a failure can never leave half a
business operation behind.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.app_env == "development",
            pool_pre_ping=True,
            # Tests run against a single connection per worker; a large pool
            # would only hold idle connections open against the test database.
            pool_size=5 if settings.is_test else 10,
            max_overflow=10,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def ping(self) -> None:
        """Readiness probe: fails when the database is unreachable."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Request-scoped session with commit-on-success semantics."""
    database: Database = request.app.state.database

    async with database.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
