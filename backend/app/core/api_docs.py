"""The interactive description of the API, served without a CDN.

By default the framework points Swagger UI at a public CDN, so the page stays
blank on a machine without internet access. The bundle ships with a pinned
package instead, and the page loads the three files it needs from under its own
path, through the same origin and the same proxy rule as the API itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

import fastapi_offline
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import FileResponse, HTMLResponse

__all__ = ["SWAGGER_UI_ASSETS", "install_swagger_ui"]

#: The package keeps the bundle next to its own code.
_ASSET_DIR: Final = Path(fastapi_offline.__file__).resolve().parent / "static"

#: File name → media type. Set explicitly rather than guessed from the
#: extension: on Windows the registry may map `.js` to `text/plain`, and with
#: `nosniff` the browser then refuses to run the bundle.
SWAGGER_UI_ASSETS: Final[dict[str, str]] = {
    "swagger-ui-bundle.js": "text/javascript; charset=utf-8",
    "swagger-ui.css": "text/css; charset=utf-8",
    "favicon.png": "image/png",
}


def _asset_endpoint(path: Path, media_type: str) -> Callable[[Request], Awaitable[FileResponse]]:
    async def asset(_request: Request) -> FileResponse:
        return FileResponse(path, media_type=media_type)

    return asset


def install_swagger_ui(
    app: FastAPI, *, docs_url: str, openapi_url: str, oauth2_redirect_url: str
) -> None:
    """Mounts the docs page, its OAuth2 redirect and the files the page loads."""
    missing = [name for name in SWAGGER_UI_ASSETS if not (_ASSET_DIR / name).is_file()]
    if missing:
        # A broken install is reported at boot, not as a blank page later.
        message = f"Swagger UI assets are missing from {_ASSET_DIR}: {', '.join(missing)}"
        raise RuntimeError(message)

    async def swagger_ui_html(request: Request) -> HTMLResponse:
        # Behind a proxy that strips a prefix every URL the page builds has to
        # carry that prefix back, exactly as the framework's own page does.
        root_path = str(request.scope.get("root_path", "")).rstrip("/")
        return get_swagger_ui_html(
            openapi_url=f"{root_path}{openapi_url}",
            title=f"{app.title} - Swagger UI",
            swagger_js_url=f"{root_path}{docs_url}/swagger-ui-bundle.js",
            swagger_css_url=f"{root_path}{docs_url}/swagger-ui.css",
            swagger_favicon_url=f"{root_path}{docs_url}/favicon.png",
            oauth2_redirect_url=f"{root_path}{oauth2_redirect_url}",
            init_oauth=app.swagger_ui_init_oauth,
            swagger_ui_parameters=app.swagger_ui_parameters,
        )

    async def swagger_ui_redirect(_request: Request) -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()

    app.add_route(docs_url, swagger_ui_html, include_in_schema=False)
    app.add_route(oauth2_redirect_url, swagger_ui_redirect, include_in_schema=False)
    for name, media_type in SWAGGER_UI_ASSETS.items():
        app.add_route(
            f"{docs_url}/{name}",
            _asset_endpoint(_ASSET_DIR / name, media_type),
            include_in_schema=False,
        )
