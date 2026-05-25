#!/usr/bin/env bash
# AskPicky container entrypoint.
#
# - `api`   (default) — uvicorn on :8000 with one worker.
# - `smoke`           — run the cheap smoke test in-container.
# - `shell`           — bash for debugging.
# - anything else     — exec it verbatim.
#
# Data dir defaults to /data (matches the VOLUME in Dockerfile + the
# compose mount). Override with `-e ASKPICKY_DATA_DIR=/elsewhere`.
set -euo pipefail

mkdir -p "${ASKPICKY_DATA_DIR:-/data}"

case "${1:-api}" in
  api)
    exec uvicorn askpicky.api.app:app \
      --host 0.0.0.0 \
      --port "${PORT:-8000}" \
      --workers 1 \
      --proxy-headers
    ;;
  smoke)
    exec python -m scripts.smoke_tests.run_all --cheap
    ;;
  shell)
    exec bash
    ;;
  *)
    exec "$@"
    ;;
esac
