#!/usr/bin/env sh
# One image, two services. The first arg selects the process.
set -e

case "${1:-api}" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec python -m app.worker
    ;;
  *)
    exec "$@"
    ;;
esac
