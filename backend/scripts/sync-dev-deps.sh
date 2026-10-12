#!/bin/sh
# Development containers keep .venv in a named volume, and Docker fills a named
# volume from the image only when it creates it. A dependency added later would
# never reach it, so the lock file is compared with the one the volume was
# installed from and the volume is brought up to date before the command runs.
set -eu
if ! cmp -s uv.lock .venv/.installed-lock; then
  echo "uv.lock changed: installing dependencies into the volume"
  uv sync --frozen --no-dev --no-install-project
  cp uv.lock .venv/.installed-lock
fi
exec "$@"
