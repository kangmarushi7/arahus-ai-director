#!/usr/bin/env sh
# Local / Railway entrypoint for Arahus Lab.
set -eu
PORT="${PORT:-8501}"
exec streamlit run app/lab.py \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true
