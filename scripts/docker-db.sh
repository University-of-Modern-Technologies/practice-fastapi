#!/bin/sh
# Starts PostgreSQL, Redis and MongoDB, then applies the migrations and the seed.
set -eu
cd "$(dirname -- "$0")/.."
for env in .env backend/.env; do
  [ -f "$env" ] || { cp "$env.example" "$env"; echo "Created $env from $env.example"; }
done
compose="docker compose -f compose.yaml -f compose.override.yaml"
$compose up -d --wait postgres redis mongo
$compose run --rm --build migrate
