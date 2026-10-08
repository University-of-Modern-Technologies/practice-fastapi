#!/bin/sh
# Stops the production stack. Databases are kept.
set -eu
cd "$(dirname -- "$0")/.."
docker compose -f compose.yaml --profile tools down --remove-orphans "$@"
