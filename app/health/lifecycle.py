"""Process lifecycle state shared between the bootstrap and the health probes.

The health router is built inside the application factory while signal handling
lives in the process bootstrap, so the two need a small piece of shared state to
agree on whether the service may still accept traffic.
"""

from __future__ import annotations

import time
from typing import Literal

LifecyclePhase = Literal["starting", "started", "draining", "stopped"]


class ServiceLifecycle:
    """Mutable phase of the running process."""

    def __init__(self) -> None:
        self._phase: LifecyclePhase = "starting"
        self._started_at: float | None = None

    @property
    def phase(self) -> LifecyclePhase:
        return self._phase

    @property
    def has_started(self) -> bool:
        """True once the listener is bound and startup work has completed."""
        return self._phase in {"started", "draining"}

    @property
    def is_accepting_traffic(self) -> bool:
        """True while the process is able to serve new requests."""
        return self._phase == "started"

    @property
    def started_for_seconds(self) -> float | None:
        if self._started_at is None:
            return None
        return time.monotonic() - self._started_at

    def mark_started(self) -> None:
        # Draining is terminal: a late start callback must never revive the
        # service after the load balancer has been told to stop sending traffic.
        if self._phase != "starting":
            return
        self._phase = "started"
        self._started_at = time.monotonic()

    def begin_draining(self) -> None:
        if self._phase == "stopped":
            return
        self._phase = "draining"

    def mark_stopped(self) -> None:
        self._phase = "stopped"

    def reset(self) -> None:
        """Returns to the initial phase. Intended for tests only."""
        self._phase = "starting"
        self._started_at = None


#: Default instance used by the health router and the process bootstrap.
service_lifecycle = ServiceLifecycle()
