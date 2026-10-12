#!/bin/sh
# docker-db.sh, then the API in Docker. The API reloads when a file is saved.
set -eu
cd "$(dirname -- "$0")/.."
sh scripts/docker-db.sh
docker compose -f compose.yaml -f compose.override.yaml up -d --build --wait --no-deps api
echo "API: http://localhost:$(sed -n 's/^API_PORT=//p' .env | head -n 1 | grep . || echo 8000)/api/docs"
