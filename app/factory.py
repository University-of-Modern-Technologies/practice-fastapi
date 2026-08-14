"""Application factory.

Builds a fully wired ASGI application and returns it without binding a socket,
which is what lets the test suite exercise the real middleware stack in-process
and lets the bootstrap stay a three-line module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.responses import ErrorResponse
from app.core.settings import Settings
from app.health.readiness import ReadinessCheck
from app.health.routes import SERVICE_VERSION, create_health_router
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.metrics import MetricsMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, RateLimitRedis
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.request_logger import RequestLoggerMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.observability import (
    create_http_metrics,
    create_metrics_registry,
    create_metrics_router,
    register_process_metrics,
)
from app.realtime.gateway import RealtimeGateway, create_realtime_router

API_PREFIX = "/api/v1"
DOCS_URL = "/docs"
OPENAPI_URL = "/openapi.json"

# The interactive docs load their bundle from a CDN, so the content policy is
# lifted for those two paths only.
_CSP_EXEMPT_PATHS = frozenset({DOCS_URL, "/docs/oauth2-redirect"})


def _install_openapi(app: FastAPI) -> None:
    """Replaces the generated schema with one that matches the real contract."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        error_schema = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = error_schema.pop("$defs", {})
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.update(definitions)
        components["ErrorResponse"] = error_schema

        error_content = {
            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
        }

        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})
                # The framework advertises 422 for schema violations; this API
                # answers 400 instead, so the generated entry would be a lie.
                responses.pop("422", None)
                responses.setdefault(
                    "400", {"description": "Invalid request", "content": error_content}
                )
                responses.setdefault(
                    "500", {"description": "Internal server error", "content": error_content}
                )

        # The 422 entries were the only referents of the framework's validation
        # models. Left behind they would document a payload this API never
        # sends, so they go out with the responses that pointed at them.
        for orphan in ("HTTPValidationError", "ValidationError"):
            components.pop(orphan, None)

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


# The argument list mirrors the optional subsystems; collapsing them into a
# config object would hide which ones a caller actually opted into.
def create_app(  # noqa: PLR0913
    settings: Settings,
    *,
    routers: list[tuple[str, APIRouter]] | None = None,
    readiness_checks: list[ReadinessCheck] | None = None,
    lifespan: Callable[..., Any] | None = None,
    rate_limit_redis: RateLimitRedis | None = None,
    realtime_gateway: RealtimeGateway | None = None,
) -> FastAPI:
    """Assembles the application from configuration and a list of routers."""
    configure_logging(settings)

    app = FastAPI(
        title="Practice CRM API",
        version=SERVICE_VERSION,
        description="Навчальна CRM API",
        docs_url=DOCS_URL,
        openapi_url=OPENAPI_URL,
        redoc_url=None,
        lifespan=lifespan,
    )
    # The lifespan does not run under the in-process test transport, so the
    # configuration is published here as well — dependencies can always read it.
    app.state.settings = settings

    metrics_registry = create_metrics_registry()
    register_process_metrics(metrics_registry)
    http_metrics = create_http_metrics(metrics_registry)
    app.state.metrics_registry = metrics_registry

    # Starlette applies middleware in reverse registration order, so this block
    # reads bottom-up: the correlation id is established first and the body
    # guard last, immediately before the route handler.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.json_body_limit_bytes)
    if rate_limit_redis is not None:
        # Between CORS and the body guard: a throttled caller must not get far
        # enough to have its body buffered, but its 429 still needs CORS headers.
        app.add_middleware(RateLimitMiddleware, redis=rate_limit_redis, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        # A wildcard is expressed as a regex because the allow-list form cannot
        # be combined with credentials.
        allow_origins=[] if settings.allows_any_origin else settings.cors_origins,
        allow_origin_regex=".*" if settings.allows_any_origin else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware, csp_exempt_paths=_CSP_EXEMPT_PATHS)
    # Outside every guard, so throttled and rejected requests are still counted.
    app.add_middleware(MetricsMiddleware, metrics=http_metrics)
    app.add_middleware(RequestLoggerMiddleware)
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app, settings)

    app.include_router(create_health_router(settings, readiness_checks), prefix="/health")

    # Metrics expose the internal topology, so the endpoint exists only when a
    # scrape token is configured to guard it.
    if settings.metrics_token:
        app.include_router(create_metrics_router(metrics_registry, settings.metrics_token))

    if realtime_gateway is not None:
        app.include_router(create_realtime_router(realtime_gateway))

    for prefix, router in routers or []:
        app.include_router(router, prefix=prefix)

    _install_openapi(app)
    return app
