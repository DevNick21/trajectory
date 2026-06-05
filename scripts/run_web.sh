#!/usr/bin/env bash
# AskPicky frontend — local dev launcher.
# Vite serves on :5173 by default; proxies /api → http://localhost:8000.
set -euo pipefail

cd "$(dirname "$0")/../apps/web"

if [ ! -d node_modules ]; then
  echo "node_modules missing — running npm install first..."
  npm install
fi

exec npm run dev
