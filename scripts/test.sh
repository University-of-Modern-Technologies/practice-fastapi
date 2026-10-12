#!/bin/sh
# Runs the backend and web client test suites. Dependencies must be installed.
set -eu
cd "$(dirname -- "$0")/.."
(cd backend && uv run pytest)
(cd frontend && npm test)
