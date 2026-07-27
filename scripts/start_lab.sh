#!/usr/bin/env sh
# Local / Railway entrypoint for Arahus Lab (FastAPI).
set -eu
PORT="${PORT:-8000}"
exec uvicorn src.webapp.main:app --host 0.0.0.0 --port "$PORT"
