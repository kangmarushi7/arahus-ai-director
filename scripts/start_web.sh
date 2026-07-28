#!/usr/bin/env sh
# Railway / Docker entry: API + Studio + Caddy on $PORT.
set -eu

PORT="${PORT:-8000}"
export PORT

echo "event=web_start port=${PORT}"

# Production FastAPI (Studio API + Lab + admin)
uvicorn src.api.app:app --host 127.0.0.1 --port 8001 &
API_PID=$!

# Next.js standalone server
(
  cd /app/studio-runtime
  PORT=3000 HOSTNAME=127.0.0.1 node server.js
) &
STUDIO_PID=$!

# Wait for API health before opening the proxy
i=0
until curl -fsS "http://127.0.0.1:8001/health" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "event=api_health_timeout"
    kill "$API_PID" "$STUDIO_PID" 2>/dev/null || true
    exit 1
  fi
  sleep 0.5
done
echo "event=api_ready"

# Caddy is the public listener on $PORT
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
