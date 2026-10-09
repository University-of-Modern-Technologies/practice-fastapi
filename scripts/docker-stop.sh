#!/bin/sh
# Stops everything this stack runs in Docker, in either mode. Databases are kept.
set -eu
cd "$(dirname -- "$0")/.."
docker compose -f compose.yaml -f compose.override.yaml --profile tools down --remove-orphans
