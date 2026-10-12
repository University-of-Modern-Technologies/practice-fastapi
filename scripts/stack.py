"""One entry point for running the stack: ``uv run poe <command>``.

Only the standard library is used, so the same commands work in PowerShell,
cmd, bash and zsh, and before the application's own dependencies matter.
"""

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
FRONTEND_ROOT = REPO_ROOT / "frontend"
COMPOSE_FILES = {
    "dev": ["compose.yaml", "compose.override.yaml"],
    "prod": ["compose.yaml"],
}
ENV_FILES = [
    (REPO_ROOT / ".env.example", REPO_ROOT / ".env"),
    (BACKEND_ROOT / ".env.example", BACKEND_ROOT / ".env"),
]
GENERATED_SECRETS = ("JWT_ACCESS_SECRET", "JWT_REFRESH_SECRET")
PORTAINER_PASSWORD_FILE = REPO_ROOT / ".portainer-password"
STORAGE_SERVICES = ["postgres", "redis", "mongo"]
PORTS = [
    ("HTTP_PORT", 8080, "application (nginx)"),
    ("API_PORT", 8000, "API"),
    ("WEB_PORT", 3000, "web client"),
    ("POSTGRES_PORT", 5432, "PostgreSQL"),
    ("REDIS_PORT", 6379, "Redis"),
    ("MONGO_PORT", 27017, "MongoDB"),
]
ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def paint(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if sys.stdout.isatty() else text


def fail(message: str, code: int = 1) -> None:
    print(paint("31", f"Error: {message}"), file=sys.stderr)
    sys.exit(code)


def read_env(path: Path = REPO_ROOT / ".env") -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ENV_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip("'\"")
    return values


def run(args: list[str], cwd: Path = REPO_ROOT, extra_env: dict[str, str] | None = None) -> None:
    executable = shutil.which(args[0])
    if executable is None:
        fail(f"{args[0]} is not installed or not in PATH", 2)
    # A nested `uv run` must pick the backend's own environment, not this one.
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    env.update(extra_env or {})
    result = subprocess.run([str(executable), *args[1:]], cwd=cwd, env=env, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def docker(args: list[str]) -> None:
    run(["docker", *args])


def compose(mode: str, args: list[str]) -> None:
    files = [flag for name in COMPOSE_FILES[mode] for flag in ("-f", name)]
    docker(["compose", *files, *args])


def require_docker() -> None:
    if shutil.which("docker") is None:
        fail("docker is not installed or not in PATH", 2)
    probe = subprocess.run(["docker", "info"], cwd=REPO_ROOT, capture_output=True, check=False)
    if probe.returncode != 0:
        fail("the Docker daemon is not responding. Start Docker Desktop and try again.", 2)


def require_env() -> None:
    for _, target in ENV_FILES:
        if not target.exists():
            name = target.relative_to(REPO_ROOT).as_posix()
            fail(f"{name} is missing. Run `uv run poe setup` first.")


def api_port() -> int:
    return int(read_env().get("API_PORT") or 8000)


def port_is_free(port: int) -> bool:
    # Binding alone is not enough on Windows: a listener on 0.0.0.0 does not stop
    # a second one on 127.0.0.1, and the two then split the traffic between them.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def write_env_file(source: Path, target: Path, values: dict[str, str]) -> None:
    lines = []
    for line in source.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{key}={values[key]}" if "=" in line and key in values else line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def portainer_password() -> str:
    if not PORTAINER_PASSWORD_FILE.exists():
        PORTAINER_PASSWORD_FILE.write_text(secrets.token_urlsafe(12), encoding="utf-8")
    return PORTAINER_PASSWORD_FILE.read_text(encoding="utf-8").strip()


def print_addresses() -> None:
    http = read_env().get("HTTP_PORT", "8080")
    password = read_env(BACKEND_ROOT / ".env").get(
        "SEED_USER_PASSWORD", "the SEED_USER_PASSWORD value from backend/.env"
    )
    print()
    print(paint("32", f"Ready: http://localhost:{http}"))
    print(f"  API docs:  http://localhost:{http}/api/docs")
    print(f"  Health:    http://localhost:{http}/api/health/ready")
    print()
    print("  Sign in as admin@crm-training.example")
    print(f"  Password:  {password}")


def ensure_installed(path: Path) -> None:
    if not (path / "node_modules").exists():
        fail(f"{path.name} dependencies are not installed. Run `uv run poe local:install`.")


# Each step starts the one before it and adds its own part: storage, then the
# API, then the web client and the proxy. The step that is already up is left
# as is, so starting a larger one over a smaller one costs seconds.


def start_storage() -> None:
    require_env()
    require_docker()
    compose("dev", ["up", "-d", "--wait", *STORAGE_SERVICES])
    # Migrations and the base seed run once and exit; what is applied is skipped.
    compose("dev", ["run", "--rm", "--build", "migrate"])


def start_api() -> None:
    start_storage()
    compose("dev", ["up", "-d", "--build", "--wait", "--no-deps", "api"])


def start_all() -> None:
    start_api()
    compose("dev", ["up", "-d", "--build", "--wait", "--no-deps", "web"])
    # After the web client, not with it: nginx resolves its upstreams on start.
    compose("dev", ["up", "-d", "--build", "--wait", "--no-deps", "nginx"])


def setup() -> None:
    existing = read_env(BACKEND_ROOT / ".env")
    generated = {key: existing.get(key) or secrets.token_urlsafe(32) for key in GENERATED_SECRETS}
    for source, target in ENV_FILES:
        name = target.relative_to(REPO_ROOT).as_posix()
        if target.exists():
            print(f"{name} already exists, left as is")
            continue
        write_env_file(source, target, generated)
        print(paint("32", f"Created {name}"))
    portainer_password()
    install_hooks()

    env = read_env()
    busy = [
        f"  {key}={env.get(key, default)} ({label})"
        for key, default, label in PORTS
        if not port_is_free(int(env.get(key, default)))
    ]
    if busy:
        print(paint("33", "\nThese ports are already taken on this machine:"))
        print("\n".join(busy))
        print(paint("33", "If it is not this stack holding them, put other values into .env."))
    print("\nNext: uv run poe docker:all")


def local_install() -> None:
    run(["uv", "sync"], cwd=BACKEND_ROOT)
    run(["npm", "ci"], cwd=FRONTEND_ROOT)


def local_api() -> None:
    # One API port for every way of running it, so the web client always finds it.
    # Two processes on one port do not fail on Windows, they split the traffic.
    require_env()
    port = api_port()
    if not port_is_free(port):
        fail(
            f"port {port} is already taken, most likely by the api container of this stack.\n"
            "Stop the containers (uv run poe docker:stop) and run local:api again."
        )
    start_storage()
    run(["uv", "run", "python", "-m", "app.main"], cwd=BACKEND_ROOT)


def local_web() -> None:
    ensure_installed(FRONTEND_ROOT)
    web_port = read_env().get("WEB_PORT") or "3000"
    run(
        ["npx", "next", "dev", "--port", web_port],
        cwd=FRONTEND_ROOT,
        extra_env={"API_ORIGIN": f"http://127.0.0.1:{api_port()}"},
    )


def docker_db() -> None:
    start_storage()
    print(paint("32", "\nStorage is up and migrated. API on this machine: uv run poe local:api"))


def docker_api() -> None:
    start_api()
    print(paint("32", f"\nAPI: http://localhost:{api_port()}/api/docs"))


def docker_all() -> None:
    start_all()
    print_addresses()


def docker_prod() -> None:
    # Builds what changed and starts it; an image that is up to date takes seconds.
    require_env()
    require_docker()
    compose("prod", ["up", "-d", "--build", "--wait"])
    print_addresses()


def docker_build() -> None:
    require_env()
    require_docker()
    compose("prod", ["build", *sys.argv[2:]])


def docker_stop() -> None:
    # Both modes share the project and its service names, so one `down` stops either.
    compose("dev", ["--profile", "tools", "down", "--remove-orphans"])


def docker_clean() -> None:
    if "--yes" not in sys.argv and "-y" not in sys.argv:
        answer = input(paint("33", 'This deletes the databases. Type "yes" to continue: '))
        if answer.strip() != "yes":
            print("Cancelled.")
            return
    compose("dev", ["--profile", "tools", "down", "--volumes", "--remove-orphans"])


def docker_logs() -> None:
    compose("dev", ["logs", "-f", "--tail=100", *sys.argv[2:]])


def docker_ps() -> None:
    compose("dev", ["ps"])


def docker_portainer() -> None:
    require_env()
    require_docker()
    password = portainer_password()
    compose("dev", ["--profile", "tools", "up", "-d", "portainer"])
    print(paint("32", f"\nPortainer: http://localhost:{read_env().get('PORTAINER_PORT', '9000')}"))
    print("  User:      admin")
    print(f"  Password:  {password}  (from {PORTAINER_PASSWORD_FILE.name})")


def migrate() -> None:
    require_env()
    compose("dev", ["run", "--rm", "migrate"])


def seed_demo() -> None:
    require_env()
    compose("dev", ["run", "--rm", "migrate", "/app/.venv/bin/python", "-m", "scripts.demo_seed"])


def test() -> None:
    run(["uv", "run", "pytest"], cwd=BACKEND_ROOT)
    run(["npm", "test"], cwd=FRONTEND_ROOT)


def check() -> None:
    # The same steps the CI jobs run, so a green `check` means a green pipeline.
    check_api()
    check_web()


def check_api() -> None:
    run(["uv", "run", "ruff", "format", "--check", "."], cwd=BACKEND_ROOT)
    run(["uv", "run", "ruff", "check", "."], cwd=BACKEND_ROOT)
    run(["uv", "run", "mypy"], cwd=BACKEND_ROOT)
    run(["uv", "run", "pytest"], cwd=BACKEND_ROOT)


def check_web() -> None:
    run(["npm", "run", "ci"], cwd=FRONTEND_ROOT)


def test_integration() -> None:
    # Talks to the storage of `docker:db`; it never starts containers itself.
    run(["uv", "run", "pytest", "-m", "integration", *sys.argv[2:]], cwd=BACKEND_ROOT)


def install_hooks() -> None:
    # prek comes with this project's dev dependencies; `install` wires it into git.
    if not (REPO_ROOT / ".git").exists():
        print(
            paint(
                "33",
                "Not a git repository: after `git init`, run setup again for the pre-commit hook.",
            )
        )
        return
    prek = shutil.which("prek")
    if prek is None:
        print(paint("33", "The pre-commit hook was not installed: prek is missing, run `uv sync`."))
        return
    result = subprocess.run(
        [prek, "install"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(paint("33", f"The pre-commit hook was not installed: {result.stderr.strip()}"))
    else:
        print(paint("32", "Installed the pre-commit hook (format and lint of staged files)"))


COMMANDS = {
    "setup": setup,
    "local:install": local_install,
    "local:api": local_api,
    "local:web": local_web,
    "docker:db": docker_db,
    "docker:api": docker_api,
    "docker:all": docker_all,
    "docker:prod": docker_prod,
    "docker:build": docker_build,
    "docker:stop": docker_stop,
    "docker:clean": docker_clean,
    "docker:logs": docker_logs,
    "docker:ps": docker_ps,
    "docker:portainer": docker_portainer,
    "db:migrate": migrate,
    "db:seed:demo": seed_demo,
    "test": test,
    "test:integration": test_integration,
    "check": check,
    "check:api": check_api,
    "check:web": check_web,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python scripts/stack.py <{'|'.join(COMMANDS)}>")
        sys.exit(1 if len(sys.argv) >= 2 else 0)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
