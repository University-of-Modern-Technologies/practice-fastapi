"""The server stops the way the sibling backend stops.

Before, the drain wait sat in the lifespan's shutdown half — which uvicorn runs
only after the listener is already closed and in-flight requests are done — so
it delayed nothing that mattered and pushed the stop past the container's
`stop_grace_period`. These tests pin the order down: readiness 503 and the drain
delay while still listening, then the listener closes, then cleanup; and the
overall timeout forces the exit.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import uvicorn

from app.core.server import EXIT_CODE_SHUTDOWN_TIMED_OUT, GracefulServer
from app.core.settings import Settings
from app.health.lifecycle import ServiceLifecycle


async def _noop_app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
    del scope, receive, send


class _Recorder:
    def __init__(self) -> None:
        self.steps: list[tuple[str, float, str]] = []
        self.started = time.monotonic()

    def note(self, step: str, lifecycle: ServiceLifecycle) -> None:
        self.steps.append((step, time.monotonic() - self.started, lifecycle.phase))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.steps]


class _FakeListener:
    def __init__(self, recorder: _Recorder, lifecycle: ServiceLifecycle) -> None:
        self._recorder = recorder
        self._lifecycle = lifecycle

    def close(self) -> None:
        self._recorder.note("listener closed", self._lifecycle)

    async def wait_closed(self) -> None:
        return None


class _FakeLifespan:
    def __init__(
        self, recorder: _Recorder, lifecycle: ServiceLifecycle, hang_for: float = 0.0
    ) -> None:
        self._recorder = recorder
        self._lifecycle = lifecycle
        self._hang_for = hang_for

    async def shutdown(self) -> None:
        await asyncio.sleep(self._hang_for)
        self._recorder.note("resources released", self._lifecycle)


def _server(
    settings: Settings,
    *,
    hang_for: float = 0.0,
    exits: list[int] | None = None,
    **overrides: int,
) -> tuple[GracefulServer, _Recorder, ServiceLifecycle]:
    configured = settings.model_copy(update=overrides)
    lifecycle = ServiceLifecycle()
    lifecycle.mark_started()
    recorder = _Recorder()
    server = GracefulServer(
        uvicorn.Config(_noop_app, timeout_graceful_shutdown=configured.graceful_shutdown_seconds),
        settings=configured,
        lifecycle=lifecycle,
        hard_exit=(exits if exits is not None else []).append,
    )
    # What `serve` would have set up before a stop could begin.
    server.servers = [_FakeListener(recorder, lifecycle)]  # type: ignore[list-item]
    server.lifespan = _FakeLifespan(recorder, lifecycle, hang_for)
    return server, recorder, lifecycle


async def test_readiness_fails_and_the_listener_drains_before_it_closes(
    settings: Settings,
) -> None:
    server, recorder, _ = _server(settings, shutdown_drain_delay_ms=100)

    await server.shutdown()

    assert recorder.names() == ["listener closed", "resources released"]
    _, closed_after, phase_at_close = recorder.steps[0]
    # The load balancer was told first, and the listener stayed open meanwhile.
    assert phase_at_close == "draining"
    assert closed_after >= 0.1


async def test_without_a_drain_delay_the_listener_closes_at_once(settings: Settings) -> None:
    server, recorder, _ = _server(settings, shutdown_drain_delay_ms=0)

    await server.shutdown()

    _, closed_after, _ = recorder.steps[0]
    assert closed_after < 0.1


async def test_a_stop_that_runs_out_of_time_forces_the_exit(settings: Settings) -> None:
    exits: list[int] = []
    server, _, _ = _server(settings, hang_for=5.0, exits=exits, shutdown_timeout_ms=50)

    stop = asyncio.create_task(server.shutdown())
    async with asyncio.timeout(2):
        while not exits:
            await asyncio.sleep(0.01)
    stop.cancel()

    assert exits == [EXIT_CODE_SHUTDOWN_TIMED_OUT]


async def test_a_stop_in_time_does_not_force_the_exit(settings: Settings) -> None:
    exits: list[int] = []
    # uvicorn's own part of the stop takes about 0.1 s; the cap is well above.
    server, _, _ = _server(settings, exits=exits, shutdown_timeout_ms=300)

    await server.shutdown()
    await asyncio.sleep(0.4)  # past the cap: the timer was cancelled, not just early

    assert exits == []


def test_the_grace_period_is_what_uvicorn_gives_in_flight_requests(settings: Settings) -> None:
    server, _, _ = _server(settings, shutdown_grace_period_ms=7_000, shutdown_timeout_ms=15_000)

    assert server.config.timeout_graceful_shutdown == 7
