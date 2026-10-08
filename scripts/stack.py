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
    ("API_PORT", 3000, "API"),
    ("WEB_PORT", 3100, "web client"),
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


def run(args: list[str], cwd: Path = REPO_ROOT) -> None:
    executable = shutil.which(args[0])
    if executable is None:
        fail(f"{args[0]} is not installed or not in PATH", 2)
    # A nested `uv run` must pick the backend's own environment, not this one.
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
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
    if not (REPO_ROOT / ".env").exists():
        fail(".env is missing. Run `uv run poe setup` first.")


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
    env = read_env()
    http = env.get("HTTP_PORT", "8080")
    print()
    print(paint("32", f"Ready: http://localhost:{http}"))
    print(f"  API docs:  http://localhost:{http}/docs")
    print(f"  Health:    http://localhost:{http}/health/ready")
    print()
    print("  Sign in as admin@crm-training.example")
    print(f"  Password:  {env.get('SEED_USER_PASSWORD', 'the SEED_USER_PASSWORD value from .env')}")


def setup() -> None:
    existing = read_env()
    generated = {key: existing.get(key) or secrets.token_urlsafe(32) for key in GENERATED_SECRETS}
    for source, target in ENV_FILES:
        name = target.relative_to(REPO_ROOT).as_posix()
        if target.exists():
            print(f"{name} already exists, left as is")
            continue
        write_env_file(source, target, generated)
        print(paint("32", f"Created {name}"))
    if not (FRONTEND_ROOT / ".env.local").exists():
        shutil.copyfile(FRONTEND_ROOT / ".env.example", FRONTEND_ROOT / ".env.local")
    portainer_password()

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
    print("\nNext: uv run poe start")


def start() -> None:
    require_env()
    require_docker()
    compose("dev", ["up", "-d", "--build", "--wait", *sys.argv[2:]])
    print_addresses()


def stop() -> None:
    compose("dev", ["--profile", "tools", "down", "--remove-orphans"])


def prod_start() -> None:
    # Production images are built once by `build`; starting only builds what is missing.
    require_env()
    require_docker()
    compose("prod", ["up", "-d", "--wait", *sys.argv[2:]])
    print_addresses()


def prod_stop() -> None:
    compose("prod", ["--profile", "tools", "down", "--remove-orphans"])


def build() -> None:
    require_env()
    require_docker()
    compose("prod", ["build", *sys.argv[2:]])


def test() -> None:
    run(["uv", "run", "pytest"], cwd=BACKEND_ROOT)
    run(["npm", "test"], cwd=FRONTEND_ROOT)


def dev() -> None:
    run(["uv", "run", "python", "-m", "app.main"], cwd=BACKEND_ROOT)


def dev_web() -> None:
    run(["npm", "run", "dev"], cwd=FRONTEND_ROOT)


def start_api() -> None:
    require_env()
    require_docker()
    compose("dev", ["up", "-d", "--build", "--wait", "api"])
    print(paint("32", f"\nAPI: http://localhost:{read_env().get('API_PORT', '3000')}/docs"))


def start_infra() -> None:
    require_env()
    require_docker()
    compose("dev", ["up", "-d", "--wait", *STORAGE_SERVICES])
    print(paint("32", "\nStorage is up. Start the API on this machine: uv run poe dev"))


def clean() -> None:
    if "--yes" not in sys.argv and "-y" not in sys.argv:
        answer = input(paint("33", 'This deletes the databases. Type "yes" to continue: '))
        if answer.strip() != "yes":
            print("Cancelled.")
            return
    compose("dev", ["--profile", "tools", "down", "--volumes", "--remove-orphans"])


def logs() -> None:
    compose("dev", ["logs", "-f", "--tail=100", *sys.argv[2:]])


def ps() -> None:
    compose("dev", ["ps"])


def migrate() -> None:
    require_env()
    compose("dev", ["run", "--rm", "migrate"])


def seed_demo() -> None:
    require_env()
    compose("dev", ["run", "--rm", "migrate", "/app/.venv/bin/python", "-m", "scripts.demo_seed"])


def tools() -> None:
    require_env()
    require_docker()
    password = portainer_password()
    compose("dev", ["--profile", "tools", "up", "-d", "portainer"])
    print(paint("32", f"\nPortainer: http://localhost:{read_env().get('PORTAINER_PORT', '9000')}"))
    print("  User:      admin")
    print(f"  Password:  {password}  (from {PORTAINER_PASSWORD_FILE.name})")


COMMANDS = {
    "setup": setup,
    "start": start,
    "stop": stop,
    "prod:start": prod_start,
    "prod:stop": prod_stop,
    "build": build,
    "test": test,
    "start:api": start_api,
    "start:infra": start_infra,
    "dev": dev,
    "dev:web": dev_web,
    "clean": clean,
    "logs": logs,
    "ps": ps,
    "db:migrate": migrate,
    "db:seed:demo": seed_demo,
    "tools": tools,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python scripts/stack.py <{'|'.join(COMMANDS)}>")
        sys.exit(1 if len(sys.argv) >= 2 else 0)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
