"""Process bootstrap.

The ASGI server imports ``app`` from here. Keeping the module this small is
deliberate: the object graph lives in the container and the assembly in the
factory, where the test suite can reach both.
"""

from __future__ import annotations

import contextlib
import sys

import uvicorn
from uvicorn.supervisors import ChangeReload

from app.container import build_container
from app.core.server import GracefulServer
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


#: What uvicorn exits with when the server never started.
STARTUP_FAILURE = 3


def run() -> None:
    """Entry point for `python -m app.main`, the one way every mode starts.

    The Docker image and the development container start here too, so `HOST`,
    `PORT`, the `SHUTDOWN_*` settings and `TRUSTED_PROXIES` mean the same thing
    however the API is run. The server is built by hand rather than through
    `uvicorn.run`, which offers no way to swap in the server that stops the way
    the sibling backend does (see `app.core.server`).
    """
    reload = settings.app_env == "development"
    config = uvicorn.Config(
        # The reloader re-imports the application in a child process, so it
        # needs the import string; otherwise the object already built here is
        # served, rather than a second one assembled by importing it again.
        "app.main:app" if reload else app,
        host=settings.host,
        port=settings.port,
        reload=reload,
        # Access logging is produced by the application's own middleware, which
        # includes the correlation id; the server's version would duplicate it.
        access_log=False,
        # How long in-flight requests may finish once the listener has closed.
        timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
        # X-Forwarded-For is believed only from the configured proxies; with
        # none configured the peer address is the client.
        proxy_headers=bool(settings.trusted_proxies),
        forwarded_allow_ips=settings.trusted_proxies or None,
    )
    server = GracefulServer(config, settings=settings)

    # After a graceful stop uvicorn re-raises the signal it caught; for Ctrl+C
    # that surfaces here as KeyboardInterrupt, which is the expected way out.
    with contextlib.suppress(KeyboardInterrupt):
        if config.should_reload:
            sock = config.bind_socket()
            ChangeReload(config, target=server.run, sockets=[sock]).run()
            return
        server.run()

    if not server.started:
        sys.exit(STARTUP_FAILURE)


if __name__ == "__main__":
    run()
