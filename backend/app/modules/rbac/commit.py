"""Side effects that belong to a write, run once the write is real.

A service changes rows on the request session, and the session is committed by
the dependency that opened it, after the handler has returned. Anything the
service does to the outside world in the meantime — dropping a cached
permission set, closing a socket whose session it just revoked — happens before
the change is visible to anyone else. A concurrent request that misses the cache
in that window reads the old rows and caches them again, for the whole TTL; and
a write that later rolls back has already had its effect.

``after_commit`` keeps the call where the service already makes it and moves
only its execution: the action runs inside the commit, after the transaction
has committed and before the commit returns. The request therefore still waits
for it, so the response is not sent while the cache holds the old answer. A
transaction that rolls back drops its pending actions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.util import await_only

from app.core.logging import get_logger

__all__ = ["after_commit"]

logger = get_logger("after-commit")

#: Key in ``Session.info`` holding the actions waiting for the next commit.
_PENDING_KEY = "after_commit_actions"

#: Fallback tasks, held until they finish so the loop cannot collect them.
_detached: set[asyncio.Task[None]] = set()

AfterCommitAction = Callable[[], Awaitable[None]]


async def _run(action: AfterCommitAction) -> None:
    # The change has committed and must be reported as a success, whatever the
    # side effect does; a failure is logged rather than raised into the commit.
    try:
        await action()
    except Exception as error:
        logger.error("After-commit action failed", err=repr(error))


def _run_inside_commit(action: AfterCommitAction) -> None:
    """Runs the action to completion from the synchronous commit hook.

    ``AsyncSession.commit`` drives the ORM inside a greenlet, and ``await_only``
    lets that greenlet wait on the event loop; the commit, and so the request,
    returns only once the action is done. A commit made outside that context
    has no loop to wait on, and the action is left to run on its own.
    """
    running = _run(action)
    try:
        await_only(running)
    except MissingGreenlet:
        running.close()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(_run(action))
        _detached.add(task)
        task.add_done_callback(_detached.discard)


def _pending_actions(sync_session: Session) -> list[AfterCommitAction]:
    """The session's queue of actions, with its two hooks attached once."""
    pending: list[AfterCommitAction] | None = sync_session.info.get(_PENDING_KEY)
    if pending is not None:
        return pending

    queue: list[AfterCommitAction] = []
    sync_session.info[_PENDING_KEY] = queue

    def on_commit(_session: Session) -> None:
        actions = list(queue)
        queue.clear()
        for action in actions:
            _run_inside_commit(action)

    def on_transaction_end(_session: Session, transaction: SessionTransaction) -> None:
        # The outermost transaction is over. After a commit the queue is
        # already empty; after a rollback it is dropped, since what it was
        # meant to follow never happened.
        if transaction.parent is None:
            queue.clear()

    event.listen(sync_session, "after_commit", on_commit)
    event.listen(sync_session, "after_transaction_end", on_transaction_end)
    return queue


async def after_commit(session: AsyncSession | Any, action: AfterCommitAction) -> None:
    """Runs ``action`` once the session's transaction has committed.

    A session without the ORM event bus — a stand-in in a unit test — runs the
    action at once, which is the only thing it can honestly do.
    """
    sync_session = getattr(session, "sync_session", None)
    if not isinstance(sync_session, Session):
        await _run(action)
        return
    _pending_actions(sync_session).append(action)
