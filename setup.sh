#!/usr/bin/env bash
# One-time setup: vendored Kronos checkout, Python venv, frontend build.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3.11}"

if [ ! -d vendor/Kronos ]; then
  echo "==> Cloning Kronos (shiyu-coder/Kronos)"
  git clone --depth 1 https://github.com/shiyu-coder/Kronos.git vendor/Kronos
fi

if [ ! -d .venv ]; then
  echo "==> Creating virtualenv with $PYTHON (Kronos needs 3.10+)"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "${PYTHON#python}" .venv
  else
    "$PYTHON" -m venv .venv
  fi
fi

echo "==> Installing Python dependencies"
if command -v uv >/dev/null 2>&1; then
  VIRTUAL_ENV=.venv uv pip install -r backend/requirements.txt
else
  .venv/bin/pip install -r backend/requirements.txt
fi

echo "==> Building frontend"
(cd frontend && npm install && npm run build)

echo
echo "Setup complete. Start the app with ./run.sh  →  http://127.0.0.1:8000"
echo "Model weights (~100MB) download from Hugging Face on first launch."
