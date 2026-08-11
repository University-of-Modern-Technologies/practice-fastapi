"""HTTP metrics middleware.

Mount this near the outside of the stack — right after the correlation id and
the request logger, and ahead of every guard. A request rejected by the rate
limiter or by authentication is still a request the service handled, and a
counter that only sees the survivors cannot show a throttling incident at all.
"""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.metrics import HttpMetrics, resolve_route_label

#: Reported when the application never emitted a response start, which happens
#: when the connection was torn down mid-flight.
_ABORTED_STATUS = 499


class MetricsMiddleware:
    """Counts requests and observes their latency."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: HttpMetrics,
        route_resolver: Callable[[Scope], str] = resolve_route_label,
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.route_resolver = route_resolver

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status = _ABORTED_STATUS

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        self.metrics.requests_in_flight.inc()
        try:
            await self.app(scope, receive, send_with_status)
        except Exception:
            # The outermost error handler will turn this into a 500; record it
            # as one here too rather than as an aborted connection.
            if status == _ABORTED_STATUS:
                status = 500
            raise
        finally:
            self.metrics.requests_in_flight.dec()
            # Resolved on the way out: the route is only written into the scope
            # once the router has matched a handler.
            route = self.route_resolver(scope)
            method = str(scope.get("method", "")).upper()
            duration = perf_counter() - started_at

            self.metrics.requests_total.labels(method=method, route=route, status=str(status)).inc()
            self.metrics.request_duration.labels(method=method, route=route).observe(duration)
