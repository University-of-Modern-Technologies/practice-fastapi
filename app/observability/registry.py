"""Metrics registry.

A dedicated :class:`CollectorRegistry` is created per application rather than
using the library-wide default one. The default registry is process-global
state: two applications built in the same interpreter — which is exactly what
the test suite does — would collide on the first duplicate metric name.
"""

from __future__ import annotations

import time
from typing import Final

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client.process_collector import ProcessCollector

#: Exposition format Prometheus scrapers expect; the ``version`` parameter is
#: part of the contract and must survive untouched into the response header.
PROMETHEUS_CONTENT_TYPE: Final = "text/plain; version=0.0.4; charset=utf-8"

#: Latency histogram bounds in seconds.
DEFAULT_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

_PROCESS_STARTED_AT: Final = time.monotonic()


def create_metrics_registry() -> CollectorRegistry:
    """Fresh, isolated registry for one application instance."""
    return CollectorRegistry()


def register_process_metrics(registry: CollectorRegistry) -> None:
    """Registers a small, always-safe set of process gauges.

    No secrets and no per-request cardinality, so it is cheap to expose wherever
    the scrape endpoint is reachable at all.
    """
    uptime = Gauge(
        "process_uptime_seconds",
        "Process uptime in seconds.",
        registry=registry,
    )
    # A pull-based gauge: the value is only computed when a scrape happens, so
    # nothing has to tick it forward.
    uptime.set_function(lambda: time.monotonic() - _PROCESS_STARTED_AT)

    # Supplies process_resident_memory_bytes, process_cpu_seconds_total and
    # process_start_time_seconds. The collector reads /proc, so it contributes
    # nothing on platforms without it instead of failing the scrape.
    ProcessCollector(registry=registry)


def render_metrics(registry: CollectorRegistry) -> bytes:
    """Renders every metric in the Prometheus text exposition format."""
    return generate_latest(registry)
