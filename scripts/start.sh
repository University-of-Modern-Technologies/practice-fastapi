#!/bin/sh
# Builds and starts the development stack, then waits until every service is healthy.
set -eu
cd "$(dirname -- "$0")/.."
for env in .env backend/.env; do
  [ -f "$env" ] || { cp "$env.example" "$env"; echo "Created $env from $env.example"; }
done
docker compose -f compose.yaml -f compose.override.yaml up -d --build --wait "$@"
echo "Ready: http://localhost:$(sed -n 's/^HTTP_PORT=//p' .env | head -n 1 | grep . || echo 8080)"
