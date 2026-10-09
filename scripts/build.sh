#!/bin/sh
# Builds the production images without starting anything.
set -eu
cd "$(dirname -- "$0")/.."
for env in .env backend/.env; do
  [ -f "$env" ] || cp "$env.example" "$env"
done
docker compose -f compose.yaml build "$@"
