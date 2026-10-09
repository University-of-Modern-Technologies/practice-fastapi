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

from app.core.api_docs import install_swagger_ui
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.openapi import RESPONSE_DESCRIPTIONS, operation_id
from app.core.responses import ErrorResponse
from app.core.settings import Settings
from app.health.readiness import ReadinessCheck
from app.health.routes import SERVICE_VERSION, create_health_router
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.cache_invalidation import CacheInvalidationMiddleware
from app.middleware.metrics import MetricsMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, RateLimitRedis
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.request_logger import RequestLoggerMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.modules.analytics.cache_keys import analytics_prefix
from app.observability import (
    create_http_metrics,
    create_metrics_registry,
    create_metrics_router,
    register_process_metrics,
)
from app.realtime.gateway import RealtimeGateway, create_realtime_router

# Everything the backend serves sits under `/api`, so a single proxy rule in
# front of it routes the business API, the docs, the probes and the metrics.
API_PREFIX = "/api/v1"
DOCS_URL = "/api/docs"
OAUTH2_REDIRECT_URL = f"{DOCS_URL}/oauth2-redirect"
OPENAPI_URL = "/api/openapi.json"
HEALTH_PREFIX = "/api/health"

# The docs page and its OAuth2 redirect boot Swagger UI from an inline script,
# which the content policy's `script-src 'self'` would block, so the policy is
# lifted for those two paths only. The bundle itself is served locally.
_CSP_EXEMPT_PATHS = frozenset({DOCS_URL, OAUTH2_REDIRECT_URL})


def _can_reject_input(path: str, operation: dict[str, Any]) -> bool:
    """Whether an operation can answer 400 for what the client sent.

    A probe that reads neither a parameter nor a body has nothing to reject.
    The business API declares the answer on every operation, the few without
    input included, so a client handles it the same way everywhere.
    """
    if not path.startswith(f"{HEALTH_PREFIX}/"):
        return True
    return bool(operation.get("parameters")) or "requestBody" in operation


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

        for path, path_item in schema.get("paths", {}).items():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})
                # The framework advertises 422 for schema violations; this API
                # answers 400 instead, so the generated entry would be a lie. A
                # 422 a route declares itself is a real refusal and stays.
                if "HTTPValidationError" in str(responses.get("422", "")):
                    responses.pop("422")
                if _can_reject_input(path, operation):
                    responses.setdefault(
                        "400", {"description": RESPONSE_DESCRIPTIONS[400], "content": error_content}
                    )
                responses.setdefault(
                    "500", {"description": RESPONSE_DESCRIPTIONS[500], "content": error_content}
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
        # The framework's own docs page loads Swagger UI from a CDN; the page
        # is mounted below with local assets instead.
        docs_url=None,
        openapi_url=OPENAPI_URL if settings.api_docs_enabled else None,
        swagger_ui_oauth2_redirect_url=None,
        redoc_url=None,
        # Applied to every route as mounted, so the name is built from the
        # full path; a route that names itself would bypass the shared rule.
        generate_unique_id_function=operation_id,
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
    # Innermost of all: it has to see the status the route actually produced.
    app.add_middleware(
        CacheInvalidationMiddleware,
        prefixes=(analytics_prefix(),),
        exempt_path_prefixes=(f"{API_PREFIX}/auth",),
    )
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

    # Off means not mounted at all: the paths answer 404 like any unknown one.
    if settings.api_docs_enabled:
        install_swagger_ui(
            app,
            docs_url=DOCS_URL,
            openapi_url=OPENAPI_URL,
            oauth2_redirect_url=OAUTH2_REDIRECT_URL,
        )

    app.include_router(create_health_router(settings, readiness_checks), prefix=HEALTH_PREFIX)

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
