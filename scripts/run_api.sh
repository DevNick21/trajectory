#!/usr/bin/env bash
# Trajectory API — local dev launcher.
# Wraps uvicorn via scripts/run_api.py so the Windows asyncio policy
# is set BEFORE uvicorn creates the event loop. Without this, Playwright's
# subprocess_exec raises NotImplementedError on Windows.
# Reads API_PORT from .env (default 8000); --reload watches src/ for edits.
set -euo pipefail

cd "$(dirname "$0")/.."

exec python scripts/run_api.py
