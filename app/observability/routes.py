"""Scrape endpoint.

The endpoint is never anonymous. A scrape lists every route the service exposes
together with its traffic volume and error rate — a free map of the internal
topology — so it is mounted only when a token is configured, and it answers 404
to anyone who cannot present that token.
"""

from __future__ import annotations

import hmac
from typing import Final

from fastapi import APIRouter, Request, Response
from prometheus_client import CollectorRegistry

from app.observability.registry import PROMETHEUS_CONTENT_TYPE, render_metrics

METRICS_PATH: Final = "/metrics"

#: Shorter tokens are guessable at scrape-endpoint rates; the setting enforces
#: the same bound, and it is repeated here so a direct caller cannot bypass it.
MIN_METRICS_TOKEN_LENGTH: Final = 16

_BEARER_PREFIX: Final = "bearer "


def _presented_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith(_BEARER_PREFIX):
        return header[len(_BEARER_PREFIX) :].strip()
    return ""


def is_authorised_scrape(request: Request, token: str) -> bool:
    """Constant-time comparison of the presented bearer token."""
    presented = _presented_token(request)
    if not presented:
        return False
    # Compared as bytes: `compare_digest` raises on a non-ASCII `str`, and an
    # exception here would answer 500 where the endpoint must answer 404.
    return hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8"))


def create_metrics_router(registry: CollectorRegistry, token: str) -> APIRouter:
    """Serves the Prometheus exposition format behind a bearer token."""
    if len(token) < MIN_METRICS_TOKEN_LENGTH:
        message = (
            f"Metrics scrape token must be at least {MIN_METRICS_TOKEN_LENGTH} characters long"
        )
        raise ValueError(message)

    router = APIRouter()

    @router.get(METRICS_PATH, include_in_schema=False)
    async def metrics(request: Request) -> Response:
        if not is_authorised_scrape(request, token):
            # No challenge header and no detail: an unauthorised scraper should
            # not even learn that the endpoint exists.
            return Response(status_code=404)

        return Response(
            content=render_metrics(registry),
            media_type=PROMETHEUS_CONTENT_TYPE,
            headers={"cache-control": "no-store"},
        )

    return router
