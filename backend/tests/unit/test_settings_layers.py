from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import BACKEND_ROOT, ENV_FILES, Settings
from scripts.seed import SeedSettings

#: Every variable these tests write, cleared first so a developer's shell
#: cannot leak into the layering under test.
_LAYERED_NAMES = (
    "APP_ENV",
    "PORT",
    "API_PORT",
    "LOG_LEVEL",
    "DATABASE_URL",
    "REDIS_URL",
    "MONGODB_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "REDIS_HOST",
    "REDIS_PORT",
    "MONGO_HOST",
    "MONGO_PORT",
    "MONGO_USER",
    "MONGO_PASSWORD",
    "MONGO_DB",
    "JWT_ACCESS_SECRET",
    "JWT_REFRESH_SECRET",
)

SHARED = """\
APP_ENV=test
API_PORT=8000
POSTGRES_PORT=15432
POSTGRES_DB=practice_crm
POSTGRES_USER=practice_crm
POSTGRES_PASSWORD=practice-local-password
REDIS_PORT=16379
MONGO_PORT=27018
MONGO_DB=practice_events
MONGO_USER=practice_crm
MONGO_PASSWORD=practice-local-password
LOG_LEVEL=debug
"""

BACKEND_ONLY = """\
JWT_ACCESS_SECRET=local-development-access-secret-not-for-real-use
JWT_REFRESH_SECRET=local-development-refresh-secret-not-for-real-use
LOG_LEVEL=warning
"""


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LAYERED_NAMES:
        monkeypatch.delenv(name, raising=False)


def _layout(
    tmp_path: Path, *, shared: str = SHARED, backend: str = BACKEND_ONLY
) -> tuple[Path, Path]:
    """A repository root with a backend folder, each holding its own `.env`."""
    backend_root = tmp_path / "repo" / "backend"
    backend_root.mkdir(parents=True)
    shared_file = backend_root.parent / ".env"
    backend_file = backend_root / ".env"
    shared_file.write_text(shared, encoding="utf-8")
    backend_file.write_text(backend, encoding="utf-8")
    return shared_file, backend_file


def _load(files: tuple[Path, Path]) -> Settings:
    return Settings(_env_file=files)


def test_the_files_are_anchored_at_the_backend_folder_not_the_working_directory() -> None:
    assert Path(__file__).resolve().parents[2] == BACKEND_ROOT
    assert (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env") == ENV_FILES
    assert all(path.is_absolute() for path in ENV_FILES)


def test_the_seed_reads_the_same_files_as_the_application() -> None:
    assert SeedSettings.model_config.get("env_file") == ENV_FILES


def test_storage_urls_are_assembled_from_the_shared_parts(tmp_path: Path) -> None:
    settings = _load(_layout(tmp_path))

    assert settings.database_url == (
        "postgresql+asyncpg://practice_crm:practice-local-password@127.0.0.1:15432/practice_crm"
    )
    assert settings.redis_url == "redis://127.0.0.1:16379"
    assert settings.mongodb_url == (
        "mongodb://practice_crm:practice-local-password@127.0.0.1:27018/practice_events"
        "?authSource=admin"
    )


def test_loading_does_not_depend_on_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _layout(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    settings = _load(files)

    assert settings.database_url.endswith("@127.0.0.1:15432/practice_crm")


def test_the_backend_file_overrides_the_shared_one(tmp_path: Path) -> None:
    settings = _load(_layout(tmp_path))

    assert settings.log_level == "warning"


def test_the_process_environment_overrides_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "error")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")

    settings = _load(_layout(tmp_path))

    assert settings.log_level == "error"
    assert settings.database_url.endswith("@postgres:5432/practice_crm")


def test_an_explicit_database_url_wins_over_the_parts(tmp_path: Path) -> None:
    backend = BACKEND_ONLY + "DATABASE_URL=postgresql://other:secret@db.internal:6543/elsewhere\n"

    settings = _load(_layout(tmp_path, backend=backend))

    assert settings.database_url == "postgresql+asyncpg://other:secret@db.internal:6543/elsewhere"


def test_explicit_redis_and_mongodb_urls_win_over_the_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6400")
    monkeypatch.setenv("MONGODB_URL", "mongodb://events.internal:27100/log")

    settings = _load(_layout(tmp_path))

    assert settings.redis_url == "redis://cache.internal:6400"
    assert settings.mongodb_url == "mongodb://events.internal:27100/log"


def test_a_blank_url_is_treated_as_absent(tmp_path: Path) -> None:
    backend = BACKEND_ONLY + "DATABASE_URL=\n"

    settings = _load(_layout(tmp_path, backend=backend))

    assert settings.database_url.endswith("@127.0.0.1:15432/practice_crm")


def test_credentials_are_url_encoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd#1")
    monkeypatch.setenv("MONGO_PASSWORD", "p@ss:w/rd#1")

    settings = _load(_layout(tmp_path))

    assert settings.database_url == (
        "postgresql+asyncpg://practice_crm:p%40ss%3Aw%2Frd%231@127.0.0.1:15432/practice_crm"
    )
    assert settings.mongodb_url.startswith("mongodb://practice_crm:p%40ss%3Aw%2Frd%231@127.0.0.1")


def test_hosts_and_ports_have_loopback_defaults(tmp_path: Path) -> None:
    shared = "\n".join(
        line
        for line in SHARED.splitlines()
        if not line.startswith(("POSTGRES_PORT", "REDIS_PORT", "MONGO_PORT"))
    )

    settings = _load(_layout(tmp_path, shared=shared))

    assert settings.database_url.endswith("@127.0.0.1:5432/practice_crm")
    assert settings.redis_url == "redis://127.0.0.1:6379"
    assert "@127.0.0.1:27017/practice_events?" in settings.mongodb_url


def test_mongodb_without_credentials_has_no_auth_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MONGO_USER", "")
    monkeypatch.setenv("MONGO_PASSWORD", "")

    settings = _load(_layout(tmp_path))

    assert settings.mongodb_url == "mongodb://127.0.0.1:27018/practice_events"


def test_missing_parts_leave_the_url_missing(tmp_path: Path) -> None:
    shared = "\n".join(
        line for line in SHARED.splitlines() if not line.startswith(("POSTGRES_", "MONGO_"))
    )

    with pytest.raises(ValidationError) as caught:
        _load(_layout(tmp_path, shared=shared))

    missing = {error["loc"][0] for error in caught.value.errors() if error["type"] == "missing"}
    assert missing == {"database_url", "mongodb_url"}


def test_the_port_falls_back_to_the_shared_api_port(tmp_path: Path) -> None:
    shared = SHARED.replace("API_PORT=8000", "API_PORT=8100")

    settings = _load(_layout(tmp_path, shared=shared))

    assert settings.port == 8100


def test_an_explicit_port_wins_over_the_api_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORT", "8200")

    settings = _load(_layout(tmp_path))

    assert settings.port == 8200


def test_the_port_defaults_to_8000(tmp_path: Path) -> None:
    shared = SHARED.replace("API_PORT=8000\n", "")

    settings = _load(_layout(tmp_path, shared=shared))

    assert settings.port == 8000
