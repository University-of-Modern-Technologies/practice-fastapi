#!/bin/sh
# docker-db.sh, then the API on this machine with reload. Ctrl+C stops the API;
# the storage keeps running until docker-stop.sh.
set -eu
cd "$(dirname -- "$0")/.."
compose="docker compose -f compose.yaml -f compose.override.yaml"
# Two processes on one port do not fail on Windows, they split the traffic.
if [ -n "$($compose ps --status running -q api 2>/dev/null)" ]; then
  echo "Error: the api container is running on the same port. Run scripts/docker-stop.sh first." >&2
  exit 1
fi
sh scripts/docker-db.sh
cd backend
exec uv run python -m app.main
