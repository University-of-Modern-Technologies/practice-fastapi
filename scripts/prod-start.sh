#!/bin/sh
# Starts the stack from production images. Images missing locally are built first;
# run scripts/build.sh to rebuild the ones that exist.
set -eu
cd "$(dirname -- "$0")/.."
[ -f .env ] || { echo 'Error: .env is missing. Copy .env.example to .env first.' >&2; exit 1; }
docker compose -f compose.yaml up -d --wait "$@"
echo "Ready: http://localhost:$(sed -n 's/^HTTP_PORT=//p' .env | head -n 1 | grep . || echo 8080)"
