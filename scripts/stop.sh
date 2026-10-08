#!/bin/sh
# Stops the stack. Databases are kept; `--volumes` deletes them as well.
set -eu
cd "$(dirname -- "$0")/.."
docker compose -f compose.yaml -f compose.override.yaml --profile tools down --remove-orphans "$@"
