"""Writes the published description of the API to ``openapi.json``.

Run from the backend folder::

    uv run python -m scripts.export_openapi

The document comes from the same factory that serves ``/api/openapi.json``.
The configuration it is built with ignores the process environment and both
``.env`` files, so every machine writes the same bytes, and nothing connects to
storage: the container only wires clients, and the lifespan that would open the
connections never runs.
"""

from __future__ import annotations

import json
from typing import Any, Final, override

from fastapi import FastAPI
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from app.container import build_container
from app.core.logging import configure_logging
from app.core.settings import BACKEND_ROOT, Settings
from app.factory import create_app

__all__ = [
    "EXPORT_COMMAND",
    "OUTPUT_PATH",
    "build_app",
    "build_document",
    "main",
    "render_document",
]

OUTPUT_PATH: Final = BACKEND_ROOT / "openapi.json"
EXPORT_COMMAND: Final = "uv run python -m scripts.export_openapi"

# Placeholders, never dialled: they only have to pass validation.
_PLACEHOLDER_SECRET = "openapi-export-placeholder-secret-value"


class _ExportSettings(Settings):
    """Settings read from the constructor arguments and nowhere else."""

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # A developer's `.env` or a variable exported in the shell would
        # otherwise leak into the document and make it differ between machines.
        return (init_settings,)


def _export_settings() -> Settings:
    return _ExportSettings(
        app_env="development",
        # Quiet: the stand-in providers announce themselves at warning level.
        log_level="error",
        api_docs_enabled=True,
        database_url="postgresql://export:export@127.0.0.1:5432/export",
        jwt_access_secret=_PLACEHOLDER_SECRET,
        jwt_refresh_secret=_PLACEHOLDER_SECRET,
        redis_url="redis://127.0.0.1:6379",
        mongodb_url="mongodb://127.0.0.1:27017/export",
    )


def build_app() -> FastAPI:
    """The application exactly as the process bootstrap assembles it."""
    settings = _export_settings()
    # Before the container: wiring the stand-in providers already logs.
    configure_logging(settings)
    container = build_container(settings)
    return create_app(
        settings,
        routers=container.routers,
        readiness_checks=container.readiness_checks,
        realtime_gateway=container.gateway,
    )


def build_document() -> dict[str, Any]:
    return build_app().openapi()


def render_document(document: dict[str, Any]) -> str:
    """Sorted keys and a fixed layout, so a diff shows only real changes."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    # LF on every platform; Git decides what a checkout gets.
    OUTPUT_PATH.write_text(render_document(build_document()), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
