#!/bin/sh
# Builds what changed and starts the whole system from production images.
set -eu
cd "$(dirname -- "$0")/.."
for env in .env backend/.env; do
  [ -f "$env" ] || { cp "$env.example" "$env"; echo "Created $env from $env.example"; }
done
docker compose -f compose.yaml up -d --build --wait
echo "Ready: http://localhost:$(sed -n 's/^HTTP_PORT=//p' .env | head -n 1 | grep . || echo 8080)"
