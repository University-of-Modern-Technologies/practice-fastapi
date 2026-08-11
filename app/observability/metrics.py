"""HTTP metric definitions and the route label rule.

The label rule is the important part. A metric labelled with the raw URL grows a
new time series for every identifier a client ever requests, so the memory cost
of the registry follows traffic instead of the route table. Only the matched
route template (``/api/v1/deals/{id}``) is ever used as a label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from starlette.types import Scope

from app.observability.registry import DEFAULT_DURATION_BUCKETS

#: Route label used when no route matched: 404s, malformed URLs, probes.
UNMATCHED_ROUTE_LABEL: Final = "__unmatched__"

_DUPLICATE_SLASHES: Final = re.compile(r"/{2,}")


@dataclass(frozen=True, slots=True)
class HttpMetrics:
    """The three instruments the HTTP middleware records into."""

    requests_total: Counter
    request_duration: Histogram
    requests_in_flight: Gauge


def create_http_metrics(
    registry: CollectorRegistry,
    *,
    duration_buckets: tuple[float, ...] = DEFAULT_DURATION_BUCKETS,
) -> HttpMetrics:
    """Declares the HTTP instruments on ``registry``."""
    return HttpMetrics(
        requests_total=Counter(
            "http_requests_total",
            "Total number of HTTP requests handled by the service.",
            labelnames=("method", "route", "status"),
            registry=registry,
        ),
        request_duration=Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds.",
            labelnames=("method", "route"),
            buckets=duration_buckets,
            registry=registry,
        ),
        requests_in_flight=Gauge(
            "http_requests_in_flight",
            "Number of HTTP requests currently being processed.",
            registry=registry,
        ),
    )


def resolve_route_label(scope: Scope) -> str:
    """Derives a bounded route label from a finished request scope.

    The router writes the matched route and the captured path parameters into
    the scope while the request is handled, so this is only meaningful after the
    application has returned.

    The label is the request path with every captured parameter value put back
    into its ``:name`` placeholder, which reconstructs the full route template
    including any router prefix. Substitution is done segment by segment so a
    parameter value that happens to be a substring of a literal segment cannot
    corrupt the label.

    The colon form is the label the dashboards and alert rules are written
    against, so it is emitted here regardless of how the router spells a
    placeholder internally.
    """
    if scope.get("route") is None:
        return UNMATCHED_ROUTE_LABEL

    path = str(scope.get("path") or "/")
    params = scope.get("path_params") or {}

    if params:
        by_value = {str(value): f":{name}" for name, value in params.items()}
        # A `path` converter captures slashes, so it can never be one segment.
        for value, placeholder in by_value.items():
            if "/" in value:
                path = path.replace(value, placeholder)
        path = "/".join(by_value.get(segment, segment) for segment in path.split("/"))

    combined = _DUPLICATE_SLASHES.sub("/", path)
    if not combined:
        return "/"
    return combined[:-1] if len(combined) > 1 and combined.endswith("/") else combined
