"""Side effects of a write run once the write has committed, and not before.

A cache dropped before the commit can be rebuilt from the old
rows by a concurrent request and then served for the whole TTL. The sessions
here are real ``AsyncSession`` objects without a database: an empty transaction
still begins, commits and rolls back, which is all the hooks look at.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.commit import after_commit


def _session_in_transaction() -> AsyncSession:
    session = AsyncSession()
    session.sync_session.begin()
    return session


async def test_the_action_waits_for_the_commit() -> None:
    session = _session_in_transaction()
    ran: list[str] = []

    async def action() -> None:
        ran.append("dropped")

    await after_commit(session, action)
    assert ran == []

    await session.commit()
    assert ran == ["dropped"]


async def test_the_commit_returns_only_once_the_action_is_done() -> None:
    session = _session_in_transaction()
    ran: list[str] = []

    async def slow_action() -> None:
        await asyncio.sleep(0.01)
        ran.append("dropped")

    await after_commit(session, slow_action)
    await session.commit()

    # The request that committed is still waiting here, so its response cannot
    # leave while the cache holds the old answer.
    assert ran == ["dropped"]


async def test_a_rollback_drops_the_pending_actions() -> None:
    session = _session_in_transaction()
    ran: list[str] = []

    async def action() -> None:
        ran.append("dropped")

    await after_commit(session, action)
    await session.rollback()
    await session.commit()

    assert ran == []


async def test_actions_run_once_and_in_the_order_given() -> None:
    session = _session_in_transaction()
    ran: list[int] = []

    for number in (1, 2):

        async def action(number: int = number) -> None:
            ran.append(number)

        await after_commit(session, action)

    await session.commit()
    await session.commit()

    assert ran == [1, 2]


async def test_a_failing_action_does_not_fail_the_commit() -> None:
    session = _session_in_transaction()
    ran: list[str] = []

    async def failing() -> None:
        message = "cache unavailable"
        raise RuntimeError(message)

    async def following() -> None:
        ran.append("still ran")

    await after_commit(session, failing)
    await after_commit(session, following)
    await session.commit()

    assert ran == ["still ran"]


async def test_a_stand_in_session_runs_the_action_at_once() -> None:
    ran: list[str] = []

    async def action() -> None:
        ran.append("dropped")

    await after_commit(object(), action)

    assert ran == ["dropped"]
