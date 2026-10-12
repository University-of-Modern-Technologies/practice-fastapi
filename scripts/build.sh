#!/bin/sh
# Builds the production images without starting anything.
set -eu
cd "$(dirname -- "$0")/.."
[ -f .env ] || cp .env.example .env
docker compose -f compose.yaml build "$@"
