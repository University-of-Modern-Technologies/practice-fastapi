"""Process bootstrap.

The ASGI server imports ``app`` from here. Keeping the module this small is
deliberate: the object graph lives in the container and the assembly in the
factory, where the test suite can reach both.
"""

from __future__ import annotations

import uvicorn

from app.container import build_container
from app.core.settings import get_settings
from app.factory import create_app
from app.lifespan import build_lifespan

settings = get_settings()
container = build_container(settings)

app = create_app(
    settings,
    routers=container.routers,
    readiness_checks=container.readiness_checks,
    lifespan=build_lifespan(container),
    # The limiter loads its script into Redis as soon as it is built, so test
    # runs are left without it rather than reaching for infrastructure they
    # deliberately do not provide.
    rate_limit_redis=None if settings.is_test else container.redis,
    realtime_gateway=container.gateway,
)


def run() -> None:
    """Entry point for `python -m app.main`."""
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
        # Access logging is produced by the application's own middleware, which
        # includes the correlation id; the server's version would duplicate it.
        access_log=False,
        timeout_graceful_shutdown=settings.shutdown_timeout_ms // 1000,
    )


if __name__ == "__main__":
    run()
