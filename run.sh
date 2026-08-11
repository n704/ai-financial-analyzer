#!/usr/bin/env bash
# Start the Kronos stock evaluator (API + built UI) on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

# Lets torch fall back to CPU for the few ops MPS lacks.
export PYTORCH_ENABLE_MPS_FALLBACK=1
# KRONOS_MODEL=mini|small|base   KRONOS_DEVICE=cpu|mps|cuda:0
export KRONOS_MODEL="${KRONOS_MODEL:-small}"

if [ ! -d frontend/dist ]; then
  echo "Building frontend…"
  (cd frontend && npm install --silent && npm run build)
fi

exec .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
