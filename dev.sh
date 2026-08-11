#!/usr/bin/env bash
# Dev mode: FastAPI with reload on :8000 + Vite dev server on :5173 (proxies /api).
set -euo pipefail
cd "$(dirname "$0")"

export PYTORCH_ENABLE_MPS_FALLBACK=1
export KRONOS_MODEL="${KRONOS_MODEL:-small}"

.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000 &
API=$!
trap 'kill $API 2>/dev/null || true' EXIT INT TERM

(cd frontend && npm run dev)
