"""The HTTP server, stopping the way the sibling backend stops.

On a stop signal the sequence is the same in both backends:

1. readiness turns 503 at once, so the load balancer stops routing here, while
   the listener keeps serving for ``SHUTDOWN_DRAIN_DELAY_MS``;
2. the listener closes, idle keep-alive connections are hung up, and in-flight
   requests get ``SHUTDOWN_GRACE_PERIOD_MS`` to finish before they are cut off;
3. the application releases its resources (the lifespan's shutdown half);
4. over all of it, ``SHUTDOWN_TIMEOUT_MS``, counted from the signal, caps the
   stop: when it runs out the process exits with code 3 whatever is still
   running.

Uvicorn does steps 2 and 3 on its own. What it lacks is the drain delay before
the listener closes — by the time the lifespan hears about the stop, the
listener is already gone — and a limit on the stop as a whole. Both are added
here, and nothing else is changed.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from collections.abc import Callable

import uvicorn

from app.core.logging import get_logger
from app.core.settings import Settings
from app.health.lifecycle import ServiceLifecycle, service_lifecycle

logger = get_logger("server")

#: The exit code of a stop that ran out of time; the sibling backend's too.
EXIT_CODE_SHUTDOWN_TIMED_OUT = 3

HardExit = Callable[[int], None]


class GracefulServer(uvicorn.Server):
    """`uvicorn.Server` with a drain delay and an overall stop timeout."""

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        settings: Settings,
        lifecycle: ServiceLifecycle = service_lifecycle,
        hard_exit: HardExit = os._exit,
    ) -> None:
        super().__init__(config)
        self._settings = settings
        self._lifecycle = lifecycle
        self._hard_exit = hard_exit

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # A thread rather than a task: the cap must hold even when the event
        # loop is the thing that is stuck.
        watchdog = threading.Timer(self._settings.shutdown_timeout_ms / 1000, self._on_timeout)
        watchdog.daemon = True
        watchdog.start()
        try:
            self._lifecycle.begin_draining()
            logger.info(
                "graceful shutdown started",
                openConnections=len(self.server_state.connections),
                drainDelayMs=self._settings.shutdown_drain_delay_ms,
                gracePeriodMs=self._settings.shutdown_grace_period_ms,
                timeoutMs=self._settings.shutdown_timeout_ms,
            )
            drain_seconds = self._settings.shutdown_drain_delay_ms / 1000
            if drain_seconds > 0:
                # The listener is still open: requests that arrive before the
                # load balancer notices the 503 are served, not refused.
                await asyncio.sleep(drain_seconds)
            await super().shutdown(sockets)
        finally:
            watchdog.cancel()

    def _on_timeout(self) -> None:
        logger.critical(
            "Shutdown timed out; forcing exit", timeoutMs=self._settings.shutdown_timeout_ms
        )
        self._hard_exit(EXIT_CODE_SHUTDOWN_TIMED_OUT)
