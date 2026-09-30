"""Drops cached reads once a write has succeeded.

A report is served from the cache for minutes, and nothing in the report knows
which writes change it: a new order moves the sales figures, a stock movement
moves the stock report, a reassigned deal moves the owner table. Tracking that
per report would be a list that goes stale the first time someone adds a write
without reading it. So the rule is blunt instead: any successful write drops
the whole namespace, and the next read builds it again.

The drop happens before the response leaves. By then the request session has
committed (it closes before the response, see ``SessionDep``), so a client that
reads right after its own write never gets the figure from before it.
"""

from __future__ import annotations

from typing import Protocol

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["CacheInvalidationMiddleware", "PrefixInvalidator"]

#: Methods that may change data. Everything else is a read.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: The first status that means the write did not happen.
FIRST_REFUSAL_STATUS = 400


class PrefixInvalidator(Protocol):
    async def invalidate_prefix(self, prefix: str) -> None: ...


class CacheInvalidationMiddleware:
    """Invalidates the given cache namespaces after every successful write.

    The cache is looked up on ``app.state`` per request rather than injected:
    it is created by the lifespan, after the middleware stack has been built.
    Without one (the in-process test transport) there is nothing to drop.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        prefixes: tuple[str, ...],
        exempt_path_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.prefixes = prefixes
        # Signing in writes a session, not business data; dropping every report
        # on each login would only make the cache useless.
        self.exempt_path_prefixes = exempt_path_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in WRITE_METHODS
            or scope.get("path", "").startswith(self.exempt_path_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        cache: PrefixInvalidator | None = getattr(scope["app"].state, "cache", None)

        async def send_after_invalidation(message: Message) -> None:
            if (
                message["type"] == "http.response.start"
                and cache is not None
                and message["status"] < FIRST_REFUSAL_STATUS
            ):
                for prefix in self.prefixes:
                    await cache.invalidate_prefix(prefix)
            await send(message)

        await self.app(scope, receive, send_after_invalidation)
