#!/usr/bin/env bash
# Trajectory API — local dev launcher.
# Reads API_PORT from .env (default 8000); --reload watches src/ for edits.
set -euo pipefail

PORT="${API_PORT:-8000}"

cd "$(dirname "$0")/.."

exec uvicorn trajectory.api.app:app \
  --reload \
  --port "$PORT" \
  --host 127.0.0.1 \
  --log-level info
